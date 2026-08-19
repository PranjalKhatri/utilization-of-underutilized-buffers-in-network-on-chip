#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt


# ============================================================
# Configuration
# ============================================================

GEM5 = "./build/X86/gem5.opt"
SE_SCRIPT = "configs/deprecated/example/se.py"

VALUES = [4, 8, 16, 32, 64, 128, 256, 512]

# Default parameters from your command
DEFAULT_PARAMS = [
    "--mem-size=2GB",
    "--caches",
    "--l2cache",
    "--l1d_size=128kB",
    "--l1i_size=64kB",
    "--l1d_assoc=2",
    "--l1i_assoc=2",
    "--cacheline_size=128",
    "--l2_size=2MB",
    "--l2_assoc=16",
    # "--ruby",
    "--maxinsts=10000000",
    "-F=1000000",
    "--num-cpu=1",
]


# ============================================================
# Stats parsing
# ============================================================
def parse_stats(stats_file, cache="system.cpu.dcache"):
    patterns = {
        "hits": rf"{re.escape(cache)}\.demandHits::total\s+(\d+)",
        "misses": rf"{re.escape(cache)}\.demandMisses::total\s+(\d+)",
        "accesses": rf"{re.escape(cache)}\.demandAccesses::total\s+(\d+)",
    }

    values = {}

    with open(stats_file) as f:
        text = f.read()

    for name, pattern in patterns.items():
        match = re.search(pattern, text)

        if match is None:
            raise RuntimeError(
                f"Could not find {cache} {name} in {stats_file}"
            )

        values[name] = int(match.group(1))

    return (
        values["hits"],
        values["misses"],
        values["accesses"],
    )
# ============================================================
# Run gem5
# ============================================================

def run_gem5(bench, extra_arg, output_dir):
    """
    Run one gem5 experiment.

    gem5 writes its stats to m5out/stats.txt.
    After completion, copy that stats file into output_dir.
    """

    import shutil

    cmd = [
        GEM5,
        SE_SCRIPT,
        *DEFAULT_PARAMS,
        f"--bench={bench}",
        extra_arg,
    ]

    print("\n" + "=" * 80)
    print("Running:")
    print(" ".join(cmd))
    print(f"Output: {output_dir}")
    print("=" * 80)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Run gem5 normally.
    # Do NOT redirect stdout/stderr.
    result = subprocess.run(cmd)

    if result.returncode != 0:
        raise RuntimeError(
            f"gem5 failed for {bench}, {extra_arg}"
        )

    # gem5 writes stats here.
    stats_file = Path("m5out/stats.txt")

    if not stats_file.exists():
        raise RuntimeError(
            f"gem5 finished but {stats_file} was not found"
        )

    # Copy stats.txt to the experiment-specific directory.
    destination = output_dir / "stats.txt"

    shutil.copy2(stats_file, destination)

    print(f"\nCopied stats:")
    print(f"  {stats_file} -> {destination}")

    # Parse the copied stats file.
    hits, misses, accesses = parse_stats(destination)

    hit_rate = hits / accesses
    miss_rate = misses / accesses

    print(
        f"hits={hits:,}, "
        f"misses={misses:,}, "
        f"accesses={accesses:,}"
    )

    print(
        f"hit rate={hit_rate * 100:.4f}%, "
        f"miss rate={miss_rate * 100:.4f}%"
    )

    return {
        "hits": hits,
        "misses": misses,
        "accesses": accesses,
        "hit_rate": hit_rate,
        "miss_rate": miss_rate,
    }

# ============================================================
# Experiment 1
# ============================================================

def experiment_l1d_size(base_output):
    """
    Q1:
    NAMD
    Vary L1D size.
    """

    print("\n\n### Q1: L1D SIZE / NAMD ###")

    results = []

    for size in VALUES:

        output_dir = (
            base_output
            / "q1_l1d_size"
            / f"namd_l1d_{size}kB"
        )

        result = run_gem5(
            "namd",
            f"--l1d_size={size}kB",
            output_dir,
        )

        result["value"] = size
        results.append(result)

    save_results(
        base_output / "q1_l1d_size" / "results.csv",
        results,
        "L1D Size (KB)",
    )

    plot_results(
        results,
        xlabel="L1D Size (KB)",
        title="NAMD: L1D Size vs Hit/Miss Rate",
        output_file=base_output / "q1_l1d_size" / "plot.png",
    )


# ============================================================
# Experiment 2
# ============================================================

def experiment_cache_block(base_output):
    """
    Q2:
    MCF
    Vary cache block size.
    """

    print("\n\n### Q2: CACHE BLOCK SIZE / MCF ###")

    results = []

    for size in VALUES:
        if(size < 16):
            continue
        output_dir = (
            base_output
            / "q2_cache_block"
            / f"mcf_block_{size}B"
        )

        result = run_gem5(
            "mcf",
            f"--cacheline_size={size}",
            output_dir,
        )

        result["value"] = size
        results.append(result)

    save_results(
        base_output / "q2_cache_block" / "results.csv",
        results,
        "Cache Block Size (Bytes)",
    )

    plot_results(
        results,
        xlabel="Cache Block Size (Bytes)",
        title="MCF: Cache Block Size vs Hit/Miss Rate",
        output_file=base_output / "q2_cache_block" / "plot.png",
    )


# ============================================================
# Experiment 3
# ============================================================

def experiment_associativity(base_output):
    """
    Q3:
    Blender
    Vary L1D associativity.
    """

    print("\n\n### Q3: ASSOCIATIVITY / BLENDER ###")

    results = []

    for assoc in VALUES:

        output_dir = (
            base_output
            / "q3_associativity"
            / f"blender_assoc_{assoc}"
        )

        result = run_gem5(
            "blender",
            f"--l1d_assoc={assoc}",
            output_dir,
        )

        result["value"] = assoc
        results.append(result)

    save_results(
        base_output / "q3_associativity" / "results.csv",
        results,
        "L1D Associativity",
    )

    plot_results(
        results,
        xlabel="L1D Associativity",
        title="Blender: Associativity vs Hit/Miss Rate",
        output_file=base_output / "q3_associativity" / "plot.png",
    )


# ============================================================
# CSV
# ============================================================

def save_results(filename, results, x_label):

    filename.parent.mkdir(parents=True, exist_ok=True)

    with open(filename, "w") as f:

        f.write(
            f"{x_label},hits,misses,accesses,"
            f"hit_rate,miss_rate\n"
        )

        for r in results:
            f.write(
                f"{r['value']},"
                f"{r['hits']},"
                f"{r['misses']},"
                f"{r['accesses']},"
                f"{r['hit_rate']:.10f},"
                f"{r['miss_rate']:.10f}\n"
            )


# ============================================================
# Plotting
# ============================================================

def plot_results(results, xlabel, title, output_file):

    x = [r["value"] for r in results]

    hit_rates = [
        r["hit_rate"] * 100
        for r in results
    ]

    miss_rates = [
        r["miss_rate"] * 100
        for r in results
    ]

    plt.figure(figsize=(10, 6))

    plt.plot(
        x,
        hit_rates,
        marker="o",
        label="Hit Rate",
    )

    plt.plot(
        x,
        miss_rates,
        marker="o",
        label="Miss Rate",
    )

    plt.xlabel(xlabel)
    plt.ylabel("Rate (%)")
    plt.title(title)

    plt.grid(True)
    plt.legend()

    plt.xticks(x)

    plt.tight_layout()

    plt.savefig(output_file, dpi=200)

    plt.close()

    print(f"Plot saved to {output_file}")


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        default="experiment_results",
        help="Directory for experiment results",
    )

    parser.add_argument(
        "--q1",
        action="store_true",
        help="Run Q1: L1D size / NAMD",
    )

    parser.add_argument(
        "--q2",
        action="store_true",
        help="Run Q2: cache block size / MCF",
    )

    parser.add_argument(
        "--q3",
        action="store_true",
        help="Run Q3: associativity / Blender",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run Q1, Q2 and Q3",
    )

    args = parser.parse_args()

    base_output = Path(args.output)

    # If no experiment specified, run all.
    run_all = args.all or not (args.q1 or args.q2 or args.q3)

    if run_all or args.q1:
        experiment_l1d_size(base_output)

    if run_all or args.q2:
        experiment_cache_block(base_output)

    if run_all or args.q3:
        experiment_associativity(base_output)

    print("\nAll requested experiments completed.")


if __name__ == "__main__":
    main()