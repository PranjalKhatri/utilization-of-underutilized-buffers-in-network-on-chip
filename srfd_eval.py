#!/usr/bin/env python3
import os
import subprocess
import argparse
import csv
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
    
    # "omnetpp": {
    #     "exe": f"{BIN_DIR}/omnetpp",
    #     "input_flag": f"-c General -r 0 -n {DATA_DIR}/omnetpp/all/input/ned {DATA_DIR}/omnetpp/ref/input/omnetpp.ini",
    #     "output_flag": ""
    # }
}

def run_benchmarks(results_dir, target_benchmarks):
    os.makedirs(results_dir, exist_ok=True)
    print(f"[*] Starting data collection. Results will be saved to {results_dir}")

    for bench, config in target_benchmarks.items():
        print(f"\n=========================================")
        print(f"[*] Running Benchmark: {bench}")
        print(f"=========================================")
        
        subprocess.run(["rm", "-rf", f"{GEM5_DIR}/m5out"])
        
        # Build command string (one workload per core in the 4x4 NoC)
        cmd_str = ";".join([config["exe"]] * 16)
        
        # Build option string
        opt_list = []
        for i in range(16):
            opt = config["input_flag"]
            if config["output_flag"]:
                opt += " " + config["output_flag"].format(i)
            opt_list.append(opt.strip())
        opt_str = ";".join(opt_list)

        # Base SE command for a 16-core, 4x4 NoC
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
        subprocess.run(gem5_cmd, check=True)
        
        stats_file = f"{GEM5_DIR}/m5out/stats.txt"
        target_file = f"{results_dir}/{bench}_stats.txt"
        if os.path.exists(stats_file):
            subprocess.run(["cp", stats_file, target_file], check=True)
            print(f"[+] Saved stats to {target_file}")
        else:
            raise FileNotFoundError(
                f"gem5 completed without generating {stats_file}"
            )

def parse_stats(file_path):
    """Parse the final statistics section into a name/value mapping."""
    with open(file_path, "r", encoding="utf-8") as stats_file:
        contents = stats_file.read()

    marker = "---------- Begin Simulation Statistics ----------"
    section = contents.rsplit(marker, 1)[-1]
    values = {}
    for line in section.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0].startswith("-"):
            continue
        try:
            values[fields[0]] = float(fields[1])
        except ValueError:
            continue
    return values


def aggregate_cache_level(stats, level):
    cache_patterns = {
        "L1I": re.compile(r"system\.ruby\.l1_cntrl\d+\.L1Icache$"),
        "L1D": re.compile(r"system\.ruby\.l1_cntrl\d+\.L1Dcache$"),
        "L2": re.compile(r"system\.ruby\.l2_cntrl\d+\.L2cache$"),
    }
    suffixes = {
        "accepted_cycles": ".m_total_re_reference_cycles",
        "accepted_count": ".m_total_re_references",
        "rejected_count": ".m_re_reference_over_limit",
        "tracked_addresses": ".m_tracked_re_reference_addresses",
    }
    totals = {name: 0.0 for name in suffixes}
    caches = set()

    for stat_name, value in stats.items():
        for field, suffix in suffixes.items():
            if not stat_name.endswith(suffix):
                continue
            cache_name = stat_name[:-len(suffix)]
            if cache_patterns[level].fullmatch(cache_name):
                totals[field] += value
                caches.add(cache_name)

    if not caches:
        raise ValueError(f"No {level} re-reference statistics found")

    accepted = totals["accepted_count"]
    rejected = totals["rejected_count"]
    observed = accepted + rejected
    totals["accepted_mean_cycles"] = (
        totals["accepted_cycles"] / accepted if accepted else 0.0
    )
    totals["rejected_percentage"] = (
        100.0 * rejected / observed if observed else 0.0
    )
    totals["cache_count"] = len(caches)
    return totals


def aggregate_vc_availability(stats):
    pattern = re.compile(r"(.+\.vc_avail_Local_port\d+)::(\d+)$")
    ports = {}
    for stat_name, value in stats.items():
        match = pattern.fullmatch(stat_name)
        if match:
            ports.setdefault(match.group(1), {})[int(match.group(2))] = value

    if not ports:
        raise ValueError("No local-port VC availability statistics found")

    percentages = []
    for buckets in ports.values():
        total_cycles = sum(buckets.values())
        if total_cycles <= 0:
            continue
        all_free_index = max(buckets)
        percentages.append(100.0 * buckets[all_free_index] / total_cycles)

    if not percentages:
        raise ValueError("Local-port VC availability contains no sampled cycles")
    return sum(percentages) / len(percentages)


def require_stat(stats, name):
    value = stats.get(name)
    if value is None or not np.isfinite(value):
        raise ValueError(f"Missing or invalid statistic: {name}")
    return value


def plot_data(results_dir, target_benchmarks):
    print(f"[*] Parsing data from {results_dir} and generating plots...")
    benchmarks = list(target_benchmarks.keys())
    levels = ("L1I", "L1D", "L2")
    re_ref_data = {level: [] for level in levels}
    vc_avail_data = []
    llc_miss_data = []
    summary_rows = []

    for bench in benchmarks:
        stats_path = f"{results_dir}/{bench}_stats.txt"
        if not os.path.isfile(stats_path):
            raise FileNotFoundError(f"Missing statistics for {bench}: {stats_path}")

        stats = parse_stats(stats_path)
        level_data = {
            level: aggregate_cache_level(stats, level) for level in levels
        }
        if level_data["L2"]["accepted_count"] <= 0:
            raise ValueError(f"{bench} has zero accepted LLC re-reference samples")

        vc_availability = aggregate_vc_availability(stats)
        llc_miss = require_stat(
            stats, "system.ruby.m_missLatencyHistSeqr::mean"
        )
        vc_avail_data.append(vc_availability)
        llc_miss_data.append(llc_miss)

        for level in levels:
            data = level_data[level]
            re_ref_data[level].append(data["accepted_mean_cycles"])
            summary_rows.append({
                "benchmark": bench,
                "cache_level": level,
                "accepted_mean_cycles": data["accepted_mean_cycles"],
                "accepted_count": int(data["accepted_count"]),
                "rejected_count": int(data["rejected_count"]),
                "rejected_percentage": data["rejected_percentage"],
                "tracked_addresses": int(data["tracked_addresses"]),
                "vc_all_free_percentage": vc_availability,
                "llc_miss_penalty_cycles": llc_miss,
            })

    csv_path = f"{results_dir}/summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=summary_rows[0].keys())
        writer.writeheader()
        writer.writerows(summary_rows)

    x_positions = np.arange(len(benchmarks))
    width = 0.25
    plt.figure(figsize=(10, 5))
    for index, level in enumerate(levels):
        offset = (index - 1) * width
        plt.bar(x_positions + offset, re_ref_data[level], width, label=level)
    plt.title("Accepted Re-Reference Interval by Cache Level (<=100,000 cycles)")
    plt.ylabel("Cache cycles")
    plt.xticks(x_positions, benchmarks, rotation=45)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{results_dir}/re_reference_cycles.png")
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, vc_avail_data, color="lightgreen", edgecolor="black")
    plt.title("Local Input-Port VC Availability (All VCs Free)")
    plt.ylabel("Percentage (%)")
    plt.ylim(0, 100)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/vc_availability.png")
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, llc_miss_data, color="salmon", edgecolor="black")
    plt.title("LLC Miss Latency (Mean Penalty)")
    plt.ylabel("Cycles")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/llc_miss_penalty.png")
    plt.close()

    print(f"[+] Wrote {csv_path} and three plots.")


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