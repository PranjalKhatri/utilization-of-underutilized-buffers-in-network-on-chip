#!/usr/bin/env python3
import os
import subprocess
import argparse
import re
import datetime
import matplotlib
matplotlib.use('Agg') # Safe for headless Docker environments
import matplotlib.pyplot as plt
import numpy as np

# --- CONFIGURATION ---
GEM5_DIR = "/docker_mounted_gem5"
BIN_DIR = f"{GEM5_DIR}/cpu2017/cpu2017/binaries"
DATA_DIR = f"{GEM5_DIR}/cpu2017/cpu2017/data"

BENCHMARKS = {
    "namd": {
        "exe": f"{BIN_DIR}/namd",
        # Using the standard 'ref' dataset namd.in
        "input_flag": f"--input {DATA_DIR}/namd/ref/input/namd.in --iterations 1",
        "output_flag": "--output /tmp/namd.{}.output"
    },
    "cactus": {
        "exe": f"{BIN_DIR}/cactus",
        # Using the spec_ref.par from the ref dataset
        "input_flag": f"{DATA_DIR}/cactus/ref/input/spec_ref.par",
        "output_flag": ""
    },
    "blender": {
        "exe": f"{BIN_DIR}/blender",
        # Passes the blend file, restricts to 1 thread (since each core runs an instance), and sets frame 849
        "input_flag": f"{DATA_DIR}/blender/ref/input/sh3_no_char.blend --threads 1 -b -F Targa -x 1 -f 849",
        "output_flag": "--render-output /tmp/blender_out_{}_"
    },
    "xalancbmk": {
        "exe": f"{BIN_DIR}/xalancbmk",
        # Standard SPEC xalancbmk run: -v <xml_file> <xsl_file>
        "input_flag": f"-v {DATA_DIR}/xalancbmk/ref/input/t5.xml {DATA_DIR}/xalancbmk/ref/input/xalanc.xsl",
        "output_flag": ""
    },
    "omnetpp": {
        "exe": f"{BIN_DIR}/omnetpp",
        # OMNeT++ requires the -n flag to locate the 'ned' directory, followed by the ini file
        "input_flag": f"-c General -r 0 -n {DATA_DIR}/omnetpp/all/input/ned {DATA_DIR}/omnetpp/ref/input/omnetpp.ini",
        "output_flag": ""
    }
}

def run_benchmarks(results_dir):
    os.makedirs(results_dir, exist_ok=True)
    print(f"[*] Starting data collection. Results will be saved to {results_dir}")

    for bench, config in BENCHMARKS.items():
        print(f"\n=========================================")
        print(f"[*] Running Benchmark: {bench}")
        print(f"=========================================")
        
        subprocess.run(["rm", "-rf", f"{GEM5_DIR}/m5out"])
        
        # Build command string (16 cores)
        cmd_str = ";".join([config["exe"]] * 16)
        
        # Build option string
        opt_list = []
        for i in range(16):
            opt = config["input_flag"]
            if config["output_flag"]:
                opt += " " + config["output_flag"].format(i)
            opt_list.append(opt.strip())
        opt_str = ";".join(opt_list)

        # Base SE command with PAPER PARAMETERS
        gem5_cmd = [
            f"{GEM5_DIR}/build/X86_MOESI_CMP_directory/gem5.opt",
            f"{GEM5_DIR}/configs/deprecated/example/se.py",
            "--cpu-type=TimingSimpleCPU",
            "--sys-clock=2GHz",
            "--mem-size=2GB",
            "--num-cpus=16",
            "--num-dirs=16",
            "--num-l2caches=16",
            "--l1i_size=16kB", "--l1i_assoc=4",
            "--l1d_size=16kB", "--l1d_assoc=4",
            "--l2_size=128kB", "--l2_assoc=8",
            "--ruby",
            "--network=garnet",
            "--topology=Mesh_XY",
            "--mesh-rows=4",
            "--vcs-per-vnet=4",
            "--link-width-bits=128",
            "--router-latency=2",
            "--routing-algorithm=1",
            "-c", cmd_str,
            "-F", "1000000",
            "--maxinsts=10000000"
        ]
        
        if opt_str.strip(";"):
            gem5_cmd.extend(["-o", opt_str])

        print(f"[*] Executing gem5 for {bench}...")
        subprocess.run(gem5_cmd)
        
        stats_file = f"{GEM5_DIR}/m5out/stats.txt"
        target_file = f"{results_dir}/{bench}_stats.txt"
        if os.path.exists(stats_file):
            subprocess.run(["cp", stats_file, target_file])
            print(f"[+] Saved stats to {target_file}")
        else:
            print(f"[-] ERROR: stats.txt not generated for {bench}.")

def extract_metric(file_path, regex_pattern):
    """Averages a specific metric using regex capture groups (capturing group 1)."""
    values = []
    pattern = re.compile(regex_pattern)
    with open(file_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                try:
                    # Extract the first capture group and convert to float
                    values.append(float(match.group(1)))
                except ValueError:
                    pass
    return sum(values) / len(values) if values else 0.0

def plot_data(results_dir):
    print(f"[*] Parsing data from {results_dir} and generating plots...")
    benchmarks = list(BENCHMARKS.keys())
    
    re_ref_data = []
    vc_avail_data = []
    llc_miss_data = []
    
    for bench in benchmarks:
        stats_path = f"{results_dir}/{bench}_stats.txt"
        if not os.path.exists(stats_path):
            print(f"[-] Missing data for {bench}, substituting 0.")
            re_ref_data.append(0)
            vc_avail_data.append(0)
            llc_miss_data.append(0)
            continue
            
        # 1. Re-Reference Average (Catches the value column)
        re_ref_avg = extract_metric(stats_path, r"avg_re_reference_cycles\s+(\d+\.?\d*)")
        
        # 2. VC Availability (Catches the percentage time that 12 VCs are free)
        # Matches: system.ruby.network.routers00.vc_avail_Local_port0::12   39021721   99.63%   100.00%
        vc_avail_avg = extract_metric(stats_path, r"vc_avail_.*::12\s+\d+\s+(\d+\.\d+)%") 
        
        # 3. LLC Miss Penalty (Catches the global mean miss latency)
        # Matches: system.ruby.m_missLatencyHistSeqr::mean      56.331765
        llc_miss_avg = extract_metric(stats_path, r"system\.ruby\.m_missLatencyHistSeqr::mean\s+(\d+\.?\d*)")
        
        re_ref_data.append(re_ref_avg)
        vc_avail_data.append(vc_avail_avg)
        llc_miss_data.append(llc_miss_avg)

    # Plot 1: Re-Reference Cycles
    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, re_ref_data, color='skyblue', edgecolor='black')
    plt.title('Average Re-Reference Cycles')
    plt.ylabel('Cycles')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/re_reference_cycles.png")
    plt.close()

    # Plot 2: VC Availability (% time all 12 VCs are free)
    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, vc_avail_data, color='lightgreen', edgecolor='black')
    plt.title('VC Availability (% Time All VCs Free)')
    plt.ylabel('Percentage (%)')
    plt.ylim(0, 100)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/vc_availability.png")
    plt.close()

    # Plot 3: LLC Miss Penalty
    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, llc_miss_data, color='salmon', edgecolor='black')
    plt.title('LLC Miss Latency (Mean Penalty)')
    plt.ylabel('Latency (Cycles)')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/llc_miss_penalty.png")
    plt.close()
    
    print(f"[+] Plots successfully saved in {results_dir} as PNGs.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baseline Evaluation Framework")
    parser.add_argument("--run", action="store_true", help="Run the gem5 benchmarks and collect data")
    parser.add_argument("--plot", action="store_true", help="Parse stats and generate plots")
    parser.add_argument("--results-dir", type=str, default=f"{GEM5_DIR}/results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}", help="Directory to save/read results")
    args = parser.parse_args()

    if not args.run and not args.plot:
        parser.print_help()
        print("\nError: You must specify either --run, --plot, or both.")
        exit(1)

    if args.run:
        run_benchmarks(args.results_dir)
        
    if args.plot:
        if not os.path.exists(args.results_dir):
            print(f"[-] Error: Results directory {args.results_dir} does not exist. Cannot plot.")
            exit(1)
        plot_data(args.results_dir)