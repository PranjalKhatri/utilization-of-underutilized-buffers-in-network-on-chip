#!/usr/bin/env python3

import argparse
import re
import shutil
import subprocess
from pathlib import Path
import csv
import matplotlib.pyplot as plt


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

GEM5 = "./build/X86/gem5.opt"

CONFIG = (
    "configs/deprecated/example/"
    "gem5_library/x86-parsec-benchmarks.py"
)

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

def cache_size_string(size_kib):
    return f"{size_kib}KiB"


def result_dir(benchmark, size_kib):
    return RESULTS_DIR / benchmark / f"l1d_{size_kib}KiB"


def stats_file(benchmark, size_kib):
    return result_dir(benchmark, size_kib) / "stats.txt"


def generate_sizes(start, end):
    """
    Generate powers of two from start to end.

    Example:
        start=1, end=64
        -> 1, 2, 4, 8, 16, 32, 64
    """

    sizes = []

    size = start

    while size <= end:
        sizes.append(size)
        size *= 2

    return sizes


# ------------------------------------------------------------
# Simulation
# ------------------------------------------------------------

def run_simulation(
    benchmark,
    size_kib,
    sim_size,
    gem5_args,
):
    output_dir = result_dir(benchmark, size_kib)
    output_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 70)
    print(f"Benchmark : {benchmark}")
    print(f"L1D size  : {size_kib} KiB")
    print("=" * 70)

    command = [
        GEM5,
        CONFIG,

        "--benchmark",
        benchmark,

        "--size",
        sim_size,

        "--l1d-size",
        cache_size_string(size_kib),

        "--l1d-assoc",
        str(gem5_args.l1d_assoc),

        "--l1i-size",
        gem5_args.l1i_size,

        "--l1i-assoc",
        str(gem5_args.l1i_assoc),

        "--l2-size",
        gem5_args.l2_size,

        "--l2-assoc",
        str(gem5_args.l2_assoc),

        "--num-l2-banks",
        str(gem5_args.num_l2_banks),

        "--num-cores",
        str(gem5_args.num_cores),

        "--memory-size",
        gem5_args.memory_size,

        "--clock",
        gem5_args.clock,
    ]

    print("Running:")
    print(" ".join(command))
    print()

    # Remove stale m5out from a previous run.
    m5out = Path("m5out")

    if m5out.exists():
        shutil.rmtree(m5out)

    stdout_path = output_dir / "stdout"
    stderr_path = output_dir / "stderr"

    with open(stdout_path, "w") as stdout_file, \
        open(stderr_path, "w") as stderr_file:

        result = subprocess.run(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

    final_stats = m5out / "stats.txt"

    if result.returncode != 0:
        print(
            f"ERROR: simulation failed for "
            f"{benchmark}, {size_kib} KiB"
        )
        print(f"See: {output_dir / 'stdout'}")
        print(f"See: {output_dir / 'stderr'}")
        return False

    if not final_stats.exists():
        print(
            f"ERROR: stats.txt not found for "
            f"{benchmark}, {size_kib} KiB"
        )
        print(f"See: {output_dir / 'stdout'}")
        print(f"See: {output_dir / 'stderr'}")
        return False

    # Copy stats.txt from the default m5out.
    shutil.copy2(
        final_stats,
        output_dir / "stats.txt"
    )

    print(f"Saved: {output_dir / 'stats.txt'}")
    print(f"Saved: {output_dir / 'stdout'}")
    print(f"Saved: {output_dir / 'stderr'}")

    return True
# ------------------------------------------------------------
# Statistics
# ------------------------------------------------------------

def find_stat(stats_path, patterns):
    """
    Find the first statistics line matching any pattern.

    This is deliberately kept separate because Ruby statistic
    names can differ between gem5 versions/configurations.
    """

    text = stats_path.read_text(errors="ignore")

    for pattern in patterns:
        match = re.search(
            rf"^\s*({pattern})\s+([-+0-9.eE]+)",
            text,
            re.MULTILINE,
        )

        if match:
            return float(match.group(2)), match.group(1)

    return None, None


# def extract_stats(benchmark, sizes):
#     """
#     Extract L1D statistics.

#     IMPORTANT:
#     Update the patterns below after checking your stats.txt.
#     """

#     rows = []

#     # --------------------------------------------------------
#     # These are placeholders for the actual Ruby L1D stats.
#     # We will set these once you provide the grep output.
#     # --------------------------------------------------------

#     access_patterns = [
#         r".*l1.*d.*access.*",
#         r".*L1D.*access.*",
#     ]

#     miss_patterns = [
#         r".*l1.*d.*miss.*",
#         r".*L1D.*miss.*",
#     ]

#     hit_patterns = [
#         r".*l1.*d.*hit.*",
#         r".*L1D.*hit.*",
#     ]

#     for size in sizes:

#         path = stats_file(benchmark, size)

#         if not path.exists():
#             print(f"Missing: {path}")
#             continue

#         accesses, access_name = find_stat(
#             path,
#             access_patterns,
#         )

#         misses, miss_name = find_stat(
#             path,
#             miss_patterns,
#         )

#         hits, hit_name = find_stat(
#             path,
#             hit_patterns,
#         )

#         if accesses is None or misses is None:
#             print(
#                 f"Could not identify L1D statistics in "
#                 f"{path}"
#             )
#             continue

#         miss_rate = misses / accesses * 100

#         hit_rate = (
#             hits / accesses * 100
#             if hits is not None
#             else 100 - miss_rate
#         )

#         rows.append({
#             "size": size,
#             "accesses": accesses,
#             "hits": hits,
#             "misses": misses,
#             "hit_rate": hit_rate,
#             "miss_rate": miss_rate,
#             "access_stat": access_name,
#             "hit_stat": hit_name,
#             "miss_stat": miss_name,
#         })

#     return rows


# # ------------------------------------------------------------
# # Plot
# # ------------------------------------------------------------

# def plot_results(benchmarks, sizes):

#     plt.figure(figsize=(10, 6))

#     plotted = False

#     for benchmark in benchmarks:

#         rows = extract_stats(
#             benchmark,
#             sizes,
#         )

#         if not rows:
#             continue

#         x = [row["size"] for row in rows]
#         y = [row["miss_rate"] for row in rows]

#         plt.plot(
#             x,
#             y,
#             marker="o",
#             label=benchmark,
#         )

#         plotted = True

#     if not plotted:
#         print("No results available to plot.")
#         return

#     plt.xscale("log", base=2)

#     plt.xlabel("L1D cache size (KiB)")
#     plt.ylabel("L1D miss rate (%)")

#     plt.title(
#         "PARSEC L1D Miss Rate vs Cache Size"
#     )

#     plt.xticks(sizes, [str(x) for x in sizes])

#     plt.grid(True, which="both", alpha=0.3)

#     plt.legend()

#     plt.tight_layout()

#     output = RESULTS_DIR / "miss_rate_vs_cache_size.png"

#     RESULTS_DIR.mkdir(exist_ok=True)

#     plt.savefig(output, dpi=200)

#     print()
#     print(f"Plot saved to: {output}")

#     plt.show()


def extract_stats(benchmark, sizes):
    """
    Extract L1D and L1I statistics from all L1 controllers.

    Returns one row per:
        benchmark / cache size / controller
    """

    rows = []

    stat_re = re.compile(
        r"l1_controllers(\d+)\."
        r"(L1Dcache|L1Icache)\."
        r"m_demand_(hits|misses|accesses)"
    )

    for size in sizes:

        path = stats_file(benchmark, size)

        if not path.exists():
            print(f"Missing: {path}")
            continue

        # controller -> cache_type -> stat_type -> value
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
                cache_type = match.group(2)
                stat_type = match.group(3)

                try:
                    value = float(parts[1])
                except ValueError:
                    continue

                stats.setdefault(controller, {})
                stats[controller].setdefault(cache_type, {})
                stats[controller][cache_type][stat_type] = value

        # ----------------------------------------------------
        # Create one row for every controller
        # ----------------------------------------------------

        for controller in sorted(stats):

            for cache_type in ["L1Dcache", "L1Icache"]:

                if cache_type not in stats[controller]:
                    continue

                s = stats[controller][cache_type]

                accesses = s.get("accesses", 0)
                hits = s.get("hits", 0)
                misses = s.get("misses", 0)

                if accesses == 0:
                    print(
                        f"Warning: zero accesses for "
                        f"{benchmark}, {size} KiB, "
                        f"controller {controller}, {cache_type}"
                    )
                    continue

                miss_rate = misses / accesses * 100
                hit_rate = hits / accesses * 100

                rows.append({
                    "benchmark": benchmark,
                    "size": size,
                    "controller": controller,
                    "cache": cache_type,
                    "accesses": accesses,
                    "hits": hits,
                    "misses": misses,
                    "hit_rate": hit_rate,
                    "miss_rate": miss_rate,
                })

    return rows


# ------------------------------------------------------------
# Combined statistics
# ------------------------------------------------------------

def get_combined_stats(rows, cache_type):
    """
    Combine all L1 controllers for each cache size.
    """

    combined = {}

    for row in rows:

        if row["cache"] != cache_type:
            continue

        size = row["size"]

        if size not in combined:
            combined[size] = {
                "accesses": 0,
                "hits": 0,
                "misses": 0,
            }

        combined[size]["accesses"] += row["accesses"]
        combined[size]["hits"] += row["hits"]
        combined[size]["misses"] += row["misses"]

    result = []

    for size in sorted(combined):

        s = combined[size]

        accesses = s["accesses"]
        hits = s["hits"]
        misses = s["misses"]

        result.append({
            "size": size,
            "accesses": accesses,
            "hits": hits,
            "misses": misses,
            "hit_rate": hits / accesses * 100,
            "miss_rate": misses / accesses * 100,
        })

    return result


# ------------------------------------------------------------
# Save CSV
# ------------------------------------------------------------

def save_stats_csv(benchmark, rows):

    output = RESULTS_DIR / benchmark / "cache_stats.csv"

    output.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "benchmark",
        "size",
        "controller",
        "cache",
        "accesses",
        "hits",
        "misses",
        "hit_rate",
        "miss_rate",
    ]

    with open(output, "w", newline="") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()
        writer.writerows(rows)

    print(f"CSV saved to: {output}")


# ------------------------------------------------------------
# Plot per-core results
# ------------------------------------------------------------

def plot_per_core(benchmark, rows, cache_type, sizes):

    import matplotlib.pyplot as plt

    cache_name = "L1D" if cache_type == "L1Dcache" else "L1I"

    controllers = sorted({
        row["controller"]
        for row in rows
        if row["cache"] == cache_type
    })

    if not controllers:
        print(
            f"No {cache_name} data for {benchmark}"
        )
        return

    plt.figure(figsize=(10, 6))

    for controller in controllers:

        controller_rows = [
            row
            for row in rows
            if row["cache"] == cache_type
            and row["controller"] == controller
        ]

        controller_rows.sort(
            key=lambda row: row["size"]
        )

        x = [
            row["size"]
            for row in controller_rows
        ]

        y = [
            row["miss_rate"]
            for row in controller_rows
        ]

        plt.plot(
            x,
            y,
            marker="o",
            label=f"Core {controller}",
        )

    plt.xscale("log", base=2)

    plt.xlabel("Cache size (KiB)")
    plt.ylabel(f"{cache_name} miss rate (%)")

    plt.title(
        f"{benchmark}: {cache_name} Miss Rate vs Cache Size"
    )

    plt.xticks(
        sizes,
        [str(x) for x in sizes],
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
        / benchmark
        / f"{cache_name}_miss_rate_per_core.png"
    )

    plt.savefig(output, dpi=200)

    plt.close()

    print(f"Plot saved to: {output}")


# ------------------------------------------------------------
# Plot combined results
# ------------------------------------------------------------

def plot_combined(benchmark, rows, cache_type,sizes):

    import matplotlib.pyplot as plt

    cache_name = "L1D" if cache_type == "L1Dcache" else "L1I"

    combined = get_combined_stats(
        rows,
        cache_type,
    )

    if not combined:
        print(
            f"No combined {cache_name} data "
            f"for {benchmark}"
        )
        return

    x = [
        row["size"]
        for row in combined
    ]

    y = [
        row["miss_rate"]
        for row in combined
    ]

    plt.figure(figsize=(10, 6))

    plt.plot(
        x,
        y,
        marker="o",
    )

    plt.xscale("log", base=2)

    plt.xlabel("Cache size (KiB)")
    plt.ylabel(f"{cache_name} miss rate (%)")

    plt.title(
        f"{benchmark}: Combined {cache_name} Miss Rate vs Cache Size"
    )

    plt.xticks(
        sizes,
        [str(x) for x in sizes],
    )

    plt.grid(
        True,
        which="both",
        alpha=0.3,
    )

    plt.tight_layout()

    output = (
        RESULTS_DIR
        / benchmark
        / f"{cache_name}_miss_rate_combined.png"
    )

    plt.savefig(output, dpi=200)

    plt.close()

    print(f"Plot saved to: {output}")


# ------------------------------------------------------------
# Main plotting function
# ------------------------------------------------------------

def plot_results(benchmarks, sizes):

    for benchmark in benchmarks:

        print()
        print(
            f"Processing {benchmark}..."
        )

        rows = extract_stats(
            benchmark,
            sizes,
        )

        if not rows:
            print(
                f"No statistics available for "
                f"{benchmark}"
            )
            continue

        # Save raw extracted data
        save_stats_csv(
            benchmark,
            rows,
        )

        # L1 Data cache
        plot_per_core(
            benchmark,
            rows,
            "L1Dcache",
            sizes,
        )

        plot_combined(
            benchmark,
            rows,
            "L1Dcache",
            sizes,
        )

        # L1 Instruction cache
        plot_per_core(
            benchmark,
            rows,
            "L1Icache",
            sizes,
        )

        plot_combined(
            benchmark,
            rows,
            "L1Icache",
            sizes,
        )

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Run PARSEC benchmarks across L1D cache sizes "
            "and plot miss rate."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["run", "plot", "run-and-plot"],
        default="run-and-plot",
        help="What to do.",
    )

    parser.add_argument(
        "--benchmark",
        nargs="+",
        default=DEFAULT_BENCHMARKS,
        help="Benchmarks to run.",
    )

    parser.add_argument(
        "--sim-size",
        default="simsmall",
        choices=["simsmall", "simmedium", "simlarge"],
    )

    # --------------------------------------------------------
    # Cache size selection
    # --------------------------------------------------------

    parser.add_argument(
        "--size",
        type=int,
        help="Run exactly one L1D cache size.",
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
    # Cache/system parameters
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
        # default="256KiB",##PRANJAL
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
    print("  ", ", ".join(f"{x} KiB" for x in sizes))

    print()

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    if args.mode in ["run", "run-and-plot"]:

        for benchmark in args.benchmark:

            for size in sizes:

                success = run_simulation(
                    benchmark,
                    size,
                    args.sim_size,
                    args,
                )

                if not success:
                    print(
                        f"Skipping failed run: "
                        f"{benchmark} / {size} KiB"
                    )

    # --------------------------------------------------------
    # Plot
    # --------------------------------------------------------

    if args.mode in ["plot", "run-and-plot"]:

        plot_results(
            args.benchmark,
            sizes,
        )


if __name__ == "__main__":
    main()