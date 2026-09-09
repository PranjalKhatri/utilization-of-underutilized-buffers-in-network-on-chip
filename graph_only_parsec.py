#!/usr/bin/env python3

import argparse
import re
from pathlib import Path
import matplotlib.pyplot as plt


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

DEFAULT_BENCHMARKS = [
    "blackscholes",
    "canneal",
    "dedup",
    "fluidanimate",
]

DEFAULT_SIZES = [
    1, 2, 4, 8, 16, 32,
    64, 128, 256, 512, 1024
]

RESULTS_DIR = Path("parsec_results")


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def result_dir(benchmark, size_kib):
    return RESULTS_DIR / benchmark / f"l1d_{size_kib}KiB"


def stats_file(benchmark, size_kib):
    return result_dir(benchmark, size_kib) / "stats.txt"


def generate_sizes(start, end):
    sizes = []

    size = start

    while size <= end:
        sizes.append(size)
        size *= 2

    return sizes


# ------------------------------------------------------------
# Statistics
# ------------------------------------------------------------

def extract_stats(benchmark, sizes):
    """
    Extract and combine all L1D controllers for each cache size.

    Returns:
        {
            cache_size: miss_rate
        }
    """

    result = {}

    stat_re = re.compile(
        r"l1_controllers(\d+)\."
        r"L1Dcache\."
        r"m_demand_(hits|misses|accesses)"
    )

    for size in sizes:

        path = stats_file(benchmark, size)

        if not path.exists():
            print(f"Missing: {path}")
            continue

        # controller -> stat_type -> value
        stats = {}

        with open(path, "r") as f:

            for line in f:

                parts = line.split()

                if len(parts) < 2:
                    continue

                name = parts[0]

                match = stat_re.search(name)

                if not match:
                    continue

                controller = int(match.group(1))
                stat_type = match.group(2)

                try:
                    value = float(parts[1])
                except ValueError:
                    continue

                stats.setdefault(controller, {})
                stats[controller][stat_type] = value

        # Combine all L1D controllers
        total_accesses = 0
        total_misses = 0

        for controller in stats:

            s = stats[controller]

            total_accesses += s.get("accesses", 0)
            total_misses += s.get("misses", 0)

        if total_accesses == 0:
            print(
                f"Warning: zero L1D accesses for "
                f"{benchmark}, {size} KiB"
            )
            continue

        miss_rate = (
            total_misses / total_accesses * 100
        )

        result[size] = miss_rate

    return result


# ------------------------------------------------------------
# Plot
# ------------------------------------------------------------

def plot_results(benchmarks, sizes):

    plt.figure(figsize=(11, 7))

    plotted = False

    for benchmark in benchmarks:

        print(f"Processing {benchmark}...")

        results = extract_stats(
            benchmark,
            sizes,
        )

        if not results:
            print(
                f"No statistics available for {benchmark}"
            )
            continue

        x = sorted(results.keys())
        y = [results[size] for size in x]

        plt.plot(
            x,
            y,
            marker="o",
            linewidth=2,
            label=benchmark,
        )

        plotted = True

    if not plotted:
        print("No results available to plot.")
        return

    # --------------------------------------------------------
    # Graph formatting
    # --------------------------------------------------------

    plt.xscale("log", base=2)

    plt.xlabel("L1D cache size (KiB)")
    plt.ylabel("L1D miss rate (%)")

    plt.title(
        "PARSEC L1D Miss Rate vs Cache Size"
    )

    plt.xticks(
        sizes,
        [str(size) for size in sizes],
    )

    plt.grid(
        True,
        which="both",
        alpha=0.3,
    )

    plt.legend()

    plt.tight_layout()

    output = (
        RESULTS_DIR
        / "all_benchmarks_miss_rate_vs_cache_size.png"
    )

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    plt.savefig(
        output,
        dpi=200,
    )

    print()
    print(f"Plot saved to: {output}")

    plt.show()


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Plot PARSEC L1D miss rates from "
            "existing gem5 statistics."
        )
    )

    # --------------------------------------------------------
    # Kept for compatibility with your old script
    # --------------------------------------------------------

    parser.add_argument(
        "--mode",
        choices=["run", "plot", "run-and-plot"],
        default="plot",
        help="Only plotting is performed.",
    )

    parser.add_argument(
        "--benchmark",
        nargs="+",
        default=DEFAULT_BENCHMARKS,
        help="Benchmarks to plot.",
    )

    parser.add_argument(
        "--sim-size",
        default="simsmall",
        choices=[
            "simsmall",
            "simmedium",
            "simlarge",
        ],
    )

    # --------------------------------------------------------
    # Cache size selection
    # --------------------------------------------------------

    parser.add_argument(
        "--size",
        type=int,
        help="Plot exactly one L1D cache size.",
    )

    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start cache size in KiB.",
    )

    parser.add_argument(
        "--end",
        type=int,
        default=1024,
        help="End cache size in KiB.",
    )

    # --------------------------------------------------------
    # Kept so the command-line interface remains compatible
    # --------------------------------------------------------

    parser.add_argument(
        "--l1d-assoc",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--l1i-size",
        default="32KiB",
    )

    parser.add_argument(
        "--l1i-assoc",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--l2-size",
        default="4MiB",
    )

    parser.add_argument(
        "--l2-assoc",
        type=int,
        default=16,
    )

    parser.add_argument(
        "--num-l2-banks",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--num-cores",
        type=int,
        default=2,
    )

    parser.add_argument(
        "--memory-size",
        default="3GiB",
    )

    parser.add_argument(
        "--clock",
        default="3GHz",
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Determine cache sizes
    # --------------------------------------------------------

    if args.size is not None:
        sizes = [args.size]
    else:
        sizes = generate_sizes(
            args.start,
            args.end,
        )

    print()
    print("Benchmarks:")
    print("  ", ", ".join(args.benchmark))

    print("L1D cache sizes:")
    print(
        "  ",
        ", ".join(f"{x} KiB" for x in sizes),
    )

    print()

    # --------------------------------------------------------
    # Plot only
    # --------------------------------------------------------

    plot_results(
        args.benchmark,
        sizes,
    )


if __name__ == "__main__":
    main()