#!/usr/bin/env python3
"""Run isolated, parallel 64-core CPU2017 analogues of the SRFD paper mixes."""
import argparse
import csv
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import srfd_eval

MIXES = {
    "M1": (("mcf", 64),),
    "M2": (("namd", 64),),
    "M3": (("mcf", 16), ("cactus", 16), ("gcc", 16), ("leela", 16)),
    "M4": (("gcc", 16), ("blender", 16), ("namd", 16), ("leela", 16)),
    "M5": (("gcc", 16), ("cactus", 16), ("namd", 16), ("leela", 16)),
    "M6": (("cactus", 16), ("gcc", 16), ("mcf", 16), ("namd", 16)),
    "M7": (("cactus", 16), ("namd", 16), ("leela", 16), ("blender", 16)),
}

MODES = (
    "baseline", "db-defensive", "db-aggressive",
    "cbdb-defensive", "cbdb-aggressive", "cbdb-nocorner",
)

def expand_mix(name):
    result = []
    for benchmark, copies in MIXES[name]:
        result.extend((benchmark, srfd_eval.BENCHMARKS[benchmark])
                      for _ in range(copies))
    assert len(result) == 64
    return result

def run_one(root, mode, mix, fast_forward, maxinsts, memory,
            cpu_type="X86O3CPU", warmup_insts=100000):
    root = os.path.abspath(root)
    mode_dir = os.path.join(root, "paper", mode)
    run_dir = os.path.join(mode_dir, f"{mix}_m5out")
    if os.path.exists(run_dir):
        return {
            "benchmark": mix, "mode": mode, "profile": "paper",
            "status": "failed", "returncode": -1, "elapsed_seconds": 0,
            "error": f"refusing to overwrite existing {run_dir}",
        }
    os.makedirs(run_dir)
    processes = expand_mix(mix)
    commands, options, outputs, cwds = [], [], [], []
    for index, (name, config) in enumerate(processes):
        core_dir, option = srfd_eval.prepare_workload(run_dir, index, config)
        commands.append(config["exe"])
        options.append(option.strip())
        outputs.append(os.path.join(core_dir, "stdout.txt"))
        cwds.append(core_dir)
    command = [
        f"{srfd_eval.GEM5_DIR}/build/X86_MOESI_CMP_directory/gem5.opt",
        "-d", run_dir,
        f"{srfd_eval.GEM5_DIR}/configs/deprecated/example/se.py",
        f"--cpu-type={cpu_type}", "--sys-clock=2GHz",
        f"--mem-size={memory}", "--num-cpus=64", "--num-dirs=4",
        "--num-l2caches=64", "--l1i_size=16kB", "--l1i_assoc=4",
        "--l1d_size=16kB", "--l1d_assoc=4",
        "--l2_size=128kB", "--l2_assoc=8", "--ruby",
        "--network=garnet", "--topology=MeshDirCorners_XY",
        "--mesh-rows=8", "--vcs-per-vnet=4",
        "--buffers-per-data-vc=5", "--link-width-bits=128",
        "--router-latency=2", "--routing-algorithm=1",
        f"--srfd-mode={mode}", "-c", ";".join(commands),
        "--options=" + ";".join(options),
        "--output=" + ";".join(outputs),
        "--workload-cwds=" + ";".join(cwds),
        "-F", str(fast_forward), f"--srfd-roi-insts={maxinsts}",
        f"--srfd-warmup-insts={warmup_insts}",
        "--errout=" + ";".join(os.path.join(cwd, "stderr.txt") for cwd in cwds),
    ]
    started = time.monotonic()
    srfd_eval.write_run_manifest(run_dir, command)
    log_path = os.path.join(run_dir, "run.log")
    with open(log_path, "w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    status = {
        "benchmark": mix, "mode": mode, "profile": "paper",
        "status": "failed", "returncode": result.returncode,
        "elapsed_seconds": elapsed, "error": "",
    }
    stats_file = os.path.join(run_dir, "stats.txt")
    if result.returncode:
        status["error"] = f"gem5 failed; see {log_path}"
        return status
    if not os.path.isfile(stats_file):
        status["error"] = "missing run-local stats.txt"
        return status
    try:
        srfd_eval.validate_roi(run_dir, 64, maxinsts)
        stats = srfd_eval.parse_stats(stats_file)
        for level in ("L1I", "L1D", "L2"):
            srfd_eval.aggregate_cache_level(stats, level)
        srfd = srfd_eval.aggregate_srfd(stats, mode)
        paper = srfd_eval.aggregate_paper_metrics(stats)
        srfd_eval.validate_srfd_accounting(srfd, paper, f"{mode}/{mix}")
    except (OSError, ValueError) as error:
        status["error"] = str(error)
        return status
    link_path = os.path.join(mode_dir, f"{mix}_stats.txt")
    os.symlink(os.path.relpath(stats_file, mode_dir), link_path)
    status["status"] = "ok"
    return status

def write_status(root, mode, rows):
    path = os.path.join(root, "paper", mode, "run_status.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = ("benchmark", "mode", "profile", "status", "returncode",
              "elapsed_seconds", "error")
    with open(path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["benchmark"]))

def write_manifest(root, mixes):
    path = os.path.join(root, "paper", "mix_manifest.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(("mix", "cpu2017_analogue", "instances"))
        for mix in mixes:
            for benchmark, copies in MIXES[mix]:
                writer.writerow((mix, benchmark, copies))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--modes", default="baseline,db-defensive")
    available = [mix for mix, members in MIXES.items()
                 if all(name in srfd_eval.BENCHMARKS for name, _ in members)]
    parser.add_argument("--mixes", default=",".join(available))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--fast-forward", type=int, default=1000000)
    parser.add_argument("--mcf-fast-forward", type=int, default=100000,
                        help="System-wide fast-forward for mixes containing mcf")
    parser.add_argument("--maxinsts", type=int, default=10000000)
    parser.add_argument("--memory", default="64GB")
    parser.add_argument("--cpu-type", default="X86O3CPU",
                        choices=("TimingSimpleCPU", "X86O3CPU"))
    parser.add_argument("--warmup-insts", type=int, default=100000)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    mixes = [item.strip().upper() for item in args.mixes.split(",") if item.strip()]
    if args.jobs < 1:
        parser.error("--jobs must be at least one")
    if set(modes) - set(MODES):
        parser.error("unknown SRFD mode")
    if set(mixes) - set(MIXES):
        parser.error("unknown workload mix")
    unavailable = set(mixes) - set(available)
    if unavailable:
        parser.error("mixes contain unavailable benchmarks: " + ",".join(sorted(unavailable)))
    if args.maxinsts < 1 or args.warmup_insts < 0 or args.fast_forward < 0:
        parser.error("invalid instruction window")
    write_manifest(args.results_dir, mixes)
    rows = {mode: [] for mode in modes}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(run_one, args.results_dir, mode, mix,
                            (args.mcf_fast_forward if any(name == "mcf" for name, _ in MIXES[mix]) else args.fast_forward),
                            args.maxinsts, args.memory, args.cpu_type, args.warmup_insts):
            (mode, mix) for mode in modes for mix in mixes
        }
        for future in as_completed(futures):
            mode, mix = futures[future]
            try:
                status = future.result()
            except Exception as error:
                status = {
                    "benchmark": mix, "mode": mode, "profile": "paper",
                    "status": "failed", "returncode": -1,
                    "elapsed_seconds": 0, "error": repr(error),
                }
            rows[mode].append(status)
            write_status(args.results_dir, mode, rows[mode])
            print(f"[{status['status']}] {mode}/{mix}: "
                  f"{status['error']}", flush=True)
    if args.compare:
        failed = [row for values in rows.values() for row in values
                  if row["status"] != "ok"]
        if failed:
            raise RuntimeError("comparison skipped because one or more runs failed")
        targets = {mix: {"members": MIXES[mix]} for mix in mixes}
        srfd_eval.plot_paper_comparison(
            args.results_dir, targets, modes, "paper")
    if any(row["status"] != "ok" for values in rows.values() for row in values):
        raise SystemExit("One or more mixes failed; inspect run_status.csv")

if __name__ == "__main__":
    main()
