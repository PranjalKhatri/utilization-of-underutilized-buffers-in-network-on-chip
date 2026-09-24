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
        "input_flag": f"--input {DATA_DIR}/namd/all/input/namd.input --iterations 1",
        "output_flag": "--output /tmp/namd.{}.output"
    },
    "cactus": {
        "exe": f"{BIN_DIR}/cactus",
        "input_flag": f"{DATA_DIR}/cactus/ref/input/spec_ref.par",
        "output_flag": ""
    },
    "blender": {
        "exe": f"{BIN_DIR}/blender",
        "input_flag": f"{DATA_DIR}/blender/ref/input/sh3_no_char.blend --threads 1 -b -F Targa -x 1 -f 849",
        "output_flag": "--render-output /tmp/blender_out_{}_"
    },
    
    # --- COMMENTED OUT: xalancbmk ---
    # The SPEC 'ref' dataset for xalancbmk is incredibly memory-hungry and attempts to 
    # allocate ~40GB of RAM across 16 instances. Running this at 32GB causes gem5's VMA 
    # (Virtual Memory Allocator) to fail and panic during the simulation.
    # "xalancbmk": {
    #     "exe": f"{BIN_DIR}/xalancbmk",
    #     "input_flag": f"-v {DATA_DIR}/xalancbmk/ref/input/t5.xml {DATA_DIR}/xalancbmk/ref/input/xalanc.xsl",
    #     "output_flag": ""
    # },
    
    "omnetpp": {
        "exe": f"{BIN_DIR}/omnetpp",
        "input_flag": f"-c General -r 0 -n {DATA_DIR}/omnetpp/all/input/ned {DATA_DIR}/omnetpp/ref/input/omnetpp.ini",
        "output_flag": ""
    }
}

def run_benchmarks(results_dir, target_benchmarks):
    os.makedirs(results_dir, exist_ok=True)
    print(f"[*] Starting data collection. Results will be saved to {results_dir}")

    for bench, config in target_benchmarks.items():
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

        # Base SE command kept at 32GB Memory
        gem5_cmd = [
            f"{GEM5_DIR}/build/X86_MOESI_CMP_directory/gem5.opt",
            f"{GEM5_DIR}/configs/deprecated/example/se.py",
            "--cpu-type=TimingSimpleCPU",
            "--sys-clock=2GHz",
            "--mem-size=32GB",
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
        
        # Use --options= explicitly to prevent argparse from eating flags like `-c General`
        if opt_str.strip(";"):
            gem5_cmd.append(f"--options={opt_str}")

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
    """Averages a specific metric using regex capture groups."""
    values = []
    pattern = re.compile(regex_pattern)
    with open(file_path, 'r') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                try:
                    values.append(float(match.group(1)))
                except ValueError:
                    pass
    return sum(values) / len(values) if values else 0.0

def plot_data(results_dir, target_benchmarks):
    print(f"[*] Parsing data from {results_dir} and generating plots...")
    benchmarks = list(target_benchmarks.keys())
    
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
            
        re_ref_avg = extract_metric(stats_path, r"avg_re_reference_cycles\s+(\d+\.?\d*)")
        vc_avail_avg = extract_metric(stats_path, r"vc_avail_.*::12\s+\d+\s+(\d+\.\d+)%") 
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
    parser.add_argument("--benchmark", type=str, help="Comma-separated list of specific benchmarks to run (e.g. omnetpp,namd). Defaults to all active benchmarks.")
    args = parser.parse_args()

    if not args.run and not args.plot:
        parser.print_help()
        print("\nError: You must specify either --run, --plot, or both.")
        exit(1)

    # Filter benchmarks if the --benchmark flag is used
    if args.benchmark:
        selected_keys = [b.strip() for b in args.benchmark.split(',')]
        target_benchmarks = {k: v for k, v in BENCHMARKS.items() if k in selected_keys}
        if not target_benchmarks:
            print(f"[-] Error: None of the specified benchmarks ({args.benchmark}) were found in the configuration.")
            exit(1)
    else:
        target_benchmarks = BENCHMARKS

    if args.run:
        run_benchmarks(args.results_dir, target_benchmarks)
        
    if args.plot:
        if not os.path.exists(args.results_dir):
            print(f"[-] Error: Results directory {args.results_dir} does not exist. Cannot plot.")
            exit(1)
        plot_data(args.results_dir, target_benchmarks)