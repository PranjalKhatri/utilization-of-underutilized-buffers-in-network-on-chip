#!/usr/bin/env python3
import os
import subprocess
import argparse
import csv
import re
import datetime
import shutil
import time
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import matplotlib
matplotlib.use('Agg') # Safe for headless Docker environments
import matplotlib.pyplot as plt
import numpy as np

# --- CONFIGURATION ---
GEM5_DIR = os.path.abspath(os.environ.get("GEM5_ROOT", os.path.dirname(__file__)))
BIN_DIR = f"{GEM5_DIR}/cpu2017/cpu2017/binaries"
DATA_DIR = f"{GEM5_DIR}/cpu2017/cpu2017/data"

BENCHMARKS = {
    "gcc": {
        "exe": f"{BIN_DIR}/gcc",
        "input_flag": f"{DATA_DIR}/gcc/ref/input/gcc-pp.c -O3 -finline-limit=0 -fif-conversion -fif-conversion2",
        "output_flag": "-o /tmp/gcc_{}.s"
    },
    "mcf": {
        "exe": f"{BIN_DIR}/mcf",
        "input_flag": f"{DATA_DIR}/mcf/ref/input/inp.in",
        "output_flag": ""
    },
    "leela": {
        "exe": f"{BIN_DIR}/leela",
        "input_flag": f"{DATA_DIR}/leela/ref/input/ref.sgf",
        "output_flag": ""
    },
    # Disabled: 16 reference Parest instances exhaust memory and abort in SE mode.
    # "parest": {
    #     "exe": f"{BIN_DIR}/parest",
    #     "input_flag": f"{DATA_DIR}/parest/ref/input/ref.prm",
    #     "output_flag": ""
    # },
    "namd": {
        "exe": f"{BIN_DIR}/namd",
        "input_flag": f"--input {DATA_DIR}/namd/all/input/namd.input --iterations 100",
        "output_flag": "--output /tmp/namd.{}.output"
    },
    "cactus": {
        "exe": f"{BIN_DIR}/cactus",
        "input_flag": f"{DATA_DIR}/cactus/ref/input/spec_ref.par",
        "output_flag": ""
    },
    # Disabled: the 4x4 baseline reached invalid long-mode opcode 0x06 at
    # tick 18,799,568,000, so it cannot provide a matched SRFD comparison.
    # "blender": {
    #     "exe": f"{BIN_DIR}/blender",
    #     "input_flag": f"{DATA_DIR}/blender/ref/input/sh3_no_char.blend --threads 1 -b -F Targa -x 1 -f 849",
    #     "output_flag": "--render-output /tmp/blender_out_{}_"
    # },
    "sjeng": {
        "exe": f"{BIN_DIR}/sjeng",
        "input_flag": f"{DATA_DIR}/sjeng/ref/input/ref.txt",
        "output_flag": ""
    },
    "lbm": {
        "exe": f"{BIN_DIR}/lbm",
        "input_flag": (
            f"3000 reference.dat 0 0 "
            f"{DATA_DIR}/lbm/ref/input/100_100_130_ldc.of"
        ),
        "output_flag": "",
        # lbm writes reference.dat in its current directory.
        "isolated_cwd": True,
    },
    # Disabled: the 4x4 baseline reached an unsupported/corrupted VEX
    # 0f38:f7 instruction at tick 40,108,118,000.
    # "xz": {
    #     "exe": f"{BIN_DIR}/xz",
    #     "input_flag": (
    #         f"{DATA_DIR}/xz/all/input/input.combined.xz 250 "
    #         "a841f68f38572a49d86226b7ff5baeb31bd19dc637a922a972b2e6d1257a890f"
    #         "6a544ecab967c313e370478c74f760eb229d4eef8a8d2836d233d3e9dd1430bf "
    #         "40401484 41217675 7"
    #     ),
    #     "output_flag": ""
    # },
    "imagick": {
        "exe": f"{BIN_DIR}/imagick",
        "input_flag": (
            f"-limit disk 0 {DATA_DIR}/imagick/ref/input/refrate_input.tga "
            "-edge 41 -resample 181% -emboss 31 -colorspace YUV "
            "-mean-shift 19x19+15% -resize 30% refrate_output.tga"
        ),
        "output_flag": "",
        "isolated_cwd": True,
    },
    "omnetpp": {
        "exe": f"{BIN_DIR}/omnetpp",
        "input_flag": "-c General -r 0 omnetpp.ini",
        "output_flag": "",
        "isolated_cwd": True,
        "cwd_links": {
            "omnetpp.ini": f"{DATA_DIR}/omnetpp/ref/input/omnetpp.ini",
            "ned": f"{DATA_DIR}/omnetpp/all/input/ned",
        },
    },
    # Disabled: the 4x4 baseline dereferenced unmapped address 0x398 at
    # tick 4,379,009,000.
    # "povray": {
    #     "exe": f"{BIN_DIR}/povray",
    #     "input_flag": "SPEC-benchmark-ref.ini",
    #     "output_flag": "",
    #     "isolated_cwd": True,
    #     "cwd_links": {
    #         "SPEC-benchmark-ref.ini": (
    #             f"{DATA_DIR}/povray/ref/input/SPEC-benchmark-ref.ini"
    #         ),
    #         "SPEC-benchmark-ref.pov": (
    #             f"{DATA_DIR}/povray/ref/input/SPEC-benchmark-ref.pov"
    #         ),
    #     },
    #     "cwd_link_dir_contents": f"{DATA_DIR}/povray/all/input",
    # },
    
    # The 16-copy reference workload needs more than the paper run's 32 GB
    # simulated memory. Run xalancbmk with --memory 64GB.
    "xalancbmk": {
        "exe": f"{BIN_DIR}/xalancbmk",
        "input_flag": (
            f"-v {DATA_DIR}/xalancbmk/ref/input/t5.xml "
            f"{DATA_DIR}/xalancbmk/ref/input/xalanc.xsl"
        ),
        "output_flag": ""
    },

}

# These programs completed before producing a nonzero post-1M-fast-forward
# measurement section. Give them a shorter warmup so useful program execution
# remains after the statistics reset.
EARLY_EXIT_FAST_FORWARD_BENCHMARKS = (
    "gcc", "mcf", "sjeng", "omnetpp",
)
for _benchmark in EARLY_EXIT_FAST_FORWARD_BENCHMARKS:
    BENCHMARKS[_benchmark]["fast_forward"] = 100000

def prepare_workload(run_dir, index, config):
    """Give each simulated process its own inputs, cwd and output names."""
    cwd = os.path.join(os.path.abspath(run_dir), f"workload_{index}")
    os.makedirs(cwd, exist_ok=True)
    for name, source in config.get("cwd_links", {}).items():
        if not os.path.exists(source):
            raise FileNotFoundError(source)
        os.symlink(os.path.abspath(source), os.path.join(cwd, name))
    source_dir = config.get("cwd_link_dir_contents")
    if source_dir:
        for name in os.listdir(source_dir):
            destination = os.path.join(cwd, name)
            if not os.path.lexists(destination):
                os.symlink(os.path.abspath(os.path.join(source_dir, name)), destination)
    option = config["input_flag"]
    if config["output_flag"]:
        output = config["output_flag"].format(index).replace("/tmp/", cwd + "/")
        option += " " + output
    return cwd, option.strip()


def validate_roi(run_dir, cores, instructions):
    with open(os.path.join(run_dir, "roi_status.json"), encoding="utf-8") as source:
        report = json.load(source)
    roi = report.get("phases", {}).get("roi", {})
    counts = roi.get("instructions", [])
    if (cores < 1 or instructions < 1 or report.get("status") != "complete" or len(counts) != cores or
            roi.get("requested_instructions") != instructions or
            any(count < instructions or count > instructions + 64 for count in counts)):
        raise ValueError("Incomplete or unequal per-CPU measurement window")
    return report


def write_run_manifest(run_dir, command):
    def digest(path):
        with open(path, "rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()
    git = ["git", "-c", f"safe.directory={GEM5_DIR}"]
    changed = subprocess.check_output(
        git + ["ls-files", "-m", "-z"], cwd=GEM5_DIR).decode().split("\0")
    changed.extend(subprocess.check_output(
        git + ["ls-files", "--others", "--exclude-standard", "-z", "--",
               "src", "configs"], cwd=GEM5_DIR).decode().split("\0"))
    manifest = {
        "command": command,
        "git_head": subprocess.check_output(
            git + ["rev-parse", "HEAD"], cwd=GEM5_DIR).decode().strip(),
        "binary_sha256": digest(command[0]),
        "source_sha256": {name: digest(os.path.join(GEM5_DIR, name))
                          for name in sorted(set(changed)) if name},
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)


def run_benchmarks(results_dir, target_benchmarks, srfd_mode="baseline",
                   profile="corners-4x4", write_status=True,
                   memory="32GB", fast_forward=None, maxinsts=10000000,
                   cpu_type="X86O3CPU", warmup_insts=100000, max_tick=None,
                   srfd_reserved_vcs=0):
    if max_tick is not None and max_tick <= 0:
        raise ValueError("max_tick must be positive")
    profiles = {"development": (16, 16, 4, "Mesh_XY", 6),
                "corners-4x4": (16, 4, 4, "MeshDirCorners_XY", 4),
                "corners-4x4-6vc": (16, 4, 4, "MeshDirCorners_XY", 6),
                "paper": (64, 4, 8, "MeshDirCorners_XY", 4),
                "paper-6vc": (64, 4, 8, "MeshDirCorners_XY", 6),
                # Diagnostic topology only: the stock Mesh_XY uniformly maps
                # the two 64-controller cache layers, then attaches the four
                # remainder directory controllers to router 0.  Do not treat
                # this profile as the paper's four-corner-memory topology.
                "paper-mesh-6vc": (64, 4, 8, "Mesh_XY", 6)}
    num_cpus, num_dirs, mesh_rows, topology, vcs_per_vnet = profiles[profile]
    if not 0 <= srfd_reserved_vcs <= vcs_per_vnet:
        raise ValueError("SRFD reservation must be between zero and profile VCs")
    results_dir = os.path.abspath(results_dir)
    os.makedirs(results_dir, exist_ok=True)
    print(f"[*] Starting data collection. Results will be saved to {results_dir}")
    successful_benchmarks = {}
    status_rows = []

    for bench, config in target_benchmarks.items():
        print(f"\n=========================================")
        print(f"[*] Running Benchmark: {bench}")
        print(f"=========================================")

        target_file = f"{results_dir}/{bench}_stats.txt"
        run_dir = os.path.join(results_dir, f"{bench}_m5out")
        if os.path.exists(target_file) or os.path.exists(run_dir):
            raise ValueError(f"Refusing to overwrite existing results for {bench}: {run_dir}")
        os.makedirs(run_dir, exist_ok=True)

        prepared = [prepare_workload(run_dir, index, config)
                    for index in range(num_cpus)]
        workload_cwds = [cwd for cwd, _ in prepared]
        
        # Build command string (one workload per core in the 4x4 NoC)
        cmd_str = ";".join([config["exe"]] * num_cpus)
        
        # Build option string
        opt_list = [option for _, option in prepared]
        opt_str = ";".join(opt_list)

        # Base SE command for a 16-core, 4x4 NoC
        gem5_cmd = [
            f"{GEM5_DIR}/build/X86_MOESI_CMP_directory/gem5.opt",
            "-d", run_dir,
            f"{GEM5_DIR}/configs/deprecated/example/se.py",
            f"--cpu-type={cpu_type}",
            "--sys-clock=2GHz",
            "--prog-interval=10kHz",
            f"--mem-size={memory}",
            f"--num-cpus={num_cpus}",
            f"--num-dirs={num_dirs}",
            f"--num-l2caches={num_cpus}",
            "--l1i_size=16kB", "--l1i_assoc=4",
            "--l1d_size=16kB", "--l1d_assoc=4",
            "--l2_size=128kB", "--l2_assoc=8",
            "--ruby",
            "--network=garnet",
            f"--topology={topology}",
            f"--mesh-rows={mesh_rows}",
            f"--vcs-per-vnet={vcs_per_vnet}",
            "--buffers-per-data-vc=5",
            "--link-width-bits=128",
            "--router-latency=2",
            "--routing-algorithm=1",
            f"--srfd-mode={srfd_mode}",
            f"--srfd-reserved-vcs={srfd_reserved_vcs}",
            "-c", cmd_str,
            "-F", str(fast_forward if fast_forward is not None
                       else config.get("fast_forward", 1000000)),
            f"--srfd-roi-insts={maxinsts}",
            f"--srfd-warmup-insts={warmup_insts}",
            "--output=" + ";".join(os.path.join(cwd, "stdout.txt") for cwd in workload_cwds),
            "--errout=" + ";".join(os.path.join(cwd, "stderr.txt") for cwd in workload_cwds),
        ]
        if workload_cwds:
            gem5_cmd.append("--workload-cwds=" + ";".join(workload_cwds))
        
        # Use --options= explicitly to prevent argparse from eating flags like `-c General`
        if opt_str.strip(";"):
            gem5_cmd.append(f"--options={opt_str}")
        if max_tick is not None:
            gem5_cmd.append(f"--abs-max-tick={max_tick}")
        with open(os.path.join(run_dir, "command.json"), "w", encoding="utf-8") as output:
            json.dump(gem5_cmd, output, indent=2)
        write_run_manifest(run_dir, gem5_cmd)

        print(f"[*] Executing gem5 for {bench}...")
        started = time.monotonic()
        try:
            log_path = os.path.join(run_dir, "run.log")
            with open(log_path, "w", encoding="utf-8") as log_file:
                subprocess.run(gem5_cmd, check=True, stdout=log_file,
                               stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as error:
            print(
                f"[-] {bench} failed with return code {error.returncode}; "
                "continuing with the remaining benchmarks."
            )
            status_rows.append({"benchmark": bench, "mode": srfd_mode, "profile": profile, "status": "failed", "returncode": error.returncode, "elapsed_seconds": time.monotonic() - started, "error": "gem5 failed"})
            continue
        
        stats_file = os.path.join(run_dir, "stats.txt")
        if os.path.exists(stats_file):
            subprocess.run(["cp", stats_file, target_file], check=True)
            print(f"[+] Saved stats to {target_file}")
            try:
                validate_roi(run_dir, num_cpus, maxinsts)
                parsed = parse_stats(target_file)
                for cache_level in ("L1I", "L1D", "L2"):
                    aggregate_cache_level(parsed, cache_level)
                srfd = aggregate_srfd(parsed, srfd_mode)
                paper = aggregate_paper_metrics(parsed)
                validate_srfd_accounting(srfd, paper, bench)
            except (OSError, ValueError) as error:
                os.remove(target_file)
                print(f"[-] {bench} produced invalid statistics: {error}")
                status_rows.append({"benchmark": bench, "mode": srfd_mode, "profile": profile, "status": "failed", "returncode": 0, "elapsed_seconds": time.monotonic() - started, "error": str(error)})
                continue
            successful_benchmarks[bench] = config
            status_rows.append({"benchmark": bench, "mode": srfd_mode, "profile": profile, "status": "ok", "returncode": 0, "elapsed_seconds": time.monotonic() - started, "error": ""})
        else:
            print(
                f"[-] {bench} completed without generating {stats_file}; "
                "continuing with the remaining benchmarks."
            )
            status_rows.append({"benchmark": bench, "mode": srfd_mode, "profile": profile, "status": "failed", "returncode": 0, "elapsed_seconds": time.monotonic() - started, "error": "missing stats.txt"})

    if write_status:
        status_path = os.path.join(results_dir, "run_status.csv")
        with open(status_path, "w", newline="", encoding="utf-8") as status_file:
            fields = ("benchmark", "mode", "profile", "status", "returncode", "elapsed_seconds", "error")
            writer = csv.DictWriter(status_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(status_rows)
    return successful_benchmarks


def run_benchmarks_parallel(results_dir, target_benchmarks, srfd_mode,
                            profile, jobs, memory="32GB", fast_forward=None,
                            maxinsts=10000000, cpu_type="X86O3CPU", warmup_insts=100000,
                            srfd_reserved_vcs=0):
    """Run benchmarks concurrently; each gem5 process owns a distinct m5out."""
    os.makedirs(results_dir, exist_ok=True)
    completed = {}
    rows = []
    submitted = {}
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        for bench, config in target_benchmarks.items():
            started = time.monotonic()
            future = executor.submit(
                run_benchmarks, results_dir, {bench: config}, srfd_mode,
                profile, False, memory, fast_forward, maxinsts, cpu_type,
                warmup_insts, srfd_reserved_vcs=srfd_reserved_vcs)
            submitted[future] = (bench, config, started)
        for future in as_completed(submitted):
            bench, config, started = submitted[future]
            elapsed = time.monotonic() - started
            try:
                result = future.result()
                ok = bench in result
                error = "" if ok else f"run failed; see {bench}_m5out and its log"
            except Exception as exception:
                ok = False
                error = repr(exception)
            if ok:
                completed[bench] = config
            rows.append({
                "benchmark": bench, "mode": srfd_mode, "profile": profile,
                "status": "ok" if ok else "failed",
                "returncode": 0 if ok else -1,
                "elapsed_seconds": elapsed, "error": error,
            })
    status_path = os.path.join(results_dir, "run_status.csv")
    fields = ("benchmark", "mode", "profile", "status", "returncode",
              "elapsed_seconds", "error")
    with open(status_path, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["benchmark"]))
    return completed

def parse_stats(file_path):
    """Parse the final statistics section into a name/value mapping."""
    with open(file_path, "r", encoding="utf-8") as stats_file:
        contents = stats_file.read()

    marker = "---------- Begin Simulation Statistics ----------"
    if marker not in contents:
        raise ValueError(f"Missing simulation statistics section in {file_path}")
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
        "histogram_overflows": ".m_re_reference_histogram_overflows",
        "tracked_addresses": ".m_tracked_re_reference_addresses",
    }
    totals = {name: 0.0 for name in suffixes}
    caches = set()

    for stat_name, value in stats.items():
        # The re-reference counters use nozero. A valid quiet cache can
        # therefore omit all of them while still exporting other statistics.
        cache_name = stat_name.rsplit(".", 1)[0]
        if cache_patterns[level].fullmatch(cache_name):
            caches.add(cache_name)
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
    totals["histogram_overflow_percentage"] = (
        100.0 * totals["histogram_overflows"] / accepted if accepted else 0.0)
    totals["cache_count"] = len(caches)
    return totals


def aggregate_vc_availability(stats, all_free=False):
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
        if all_free:
            percentages.append(100.0 * buckets[all_free_index] / total_cycles)
        else:
            free_vc_cycles = sum(index * cycles for index, cycles in buckets.items())
            percentages.append(100.0 * free_vc_cycles / (all_free_index * total_cycles))

    if not percentages:
        raise ValueError("Local-port VC availability contains no sampled cycles")
    return sum(percentages) / len(percentages)


def require_stat(stats, name):
    value = stats.get(name)
    if value is None or not np.isfinite(value):
        raise ValueError(f"Missing or invalid statistic: {name}")
    return value


def aggregate_srfd(stats, mode):
    suffixes = ("dirty_offered", "clean_offered", "dirty_stored", "clean_stored",
                "dirty_forwarded", "clean_dropped", "gets_lookups", "getx_lookups",
                "clean_hits", "dirty_hits", "clean_gets_hits",
                "dirty_gets_hits", "dirty_getx_hits",
                "getx_clean_conflicts",
                "incomplete_misses", "pressure_events", "pressure_attempts",
                "pressure_no_victim", "avoided_requests", "max_stored",
                "resident")
    result = {}
    for suffix in suffixes:
        values = [value for name, value in stats.items()
                  if ".srfd_" in name and name.endswith("." + suffix)]
        if not values:
            raise ValueError(f"Missing SRFD statistic: *.{suffix}")
        result[suffix] = max(values) if suffix == "max_stored" else sum(values)
    # Older binaries have no capacity-bypass counters. A default reservation
    # of zero preserves their behavior and treats missing counters as zero.
    has_capacity_counters = any(
        ".srfd_" in name and name.endswith(".dirty_bypassed")
        for name in stats)
    for kind in ("dirty", "clean"):
        key = kind + "_bypassed"
        result[key] = sum(value for name, value in stats.items()
                         if ".srfd_" in name and name.endswith("." + key))
        opening = sum(value for name, value in stats.items()
                      if ".srfd_" in name and
                      name.endswith(".opening_staged_" + kind))
        closing = sum(value for name, value in stats.items()
                      if ".srfd_" in name and
                      name.endswith(".closing_staged_" + kind))
        result["opening_staged_" + kind] = opening
        result["closing_staged_" + kind] = closing
        if has_capacity_counters and result[kind + "_offered"] + opening != (
                result[kind + "_stored"] + result[key] + closing):
            raise ValueError("SRFD offered/stored/bypassed accounting mismatch")
    if result["pressure_attempts"] != result["pressure_events"] + result["pressure_no_victim"]:
        raise ValueError("SRFD pressure attempt accounting is unbalanced")
    result["opening_resident"] = sum(value for name, value in stats.items()
        if ".srfd_" in name and name.endswith(".opening_resident"))
    stored = result["opening_resident"] + result["dirty_stored"] + result["clean_stored"]
    retired = (result["dirty_hits"] + result["clean_hits"] +
               result["dirty_forwarded"] + result["clean_dropped"] +
               result["resident"])
    if stored != retired:
        raise ValueError("SRFD stored/hit/forward/drop/resident accounting is unbalanced")
    attempts = result["gets_lookups"] + result["getx_lookups"]
    if result["clean_hits"] != result["clean_gets_hits"]:
        raise ValueError("SRFD clean hit/type accounting is unbalanced")
    if result["dirty_hits"] != result["dirty_gets_hits"] + result["dirty_getx_hits"]:
        raise ValueError("SRFD dirty hit/type accounting is unbalanced")
    result["local_reply_rate_percentage"] = (
        100.0 * (result["clean_hits"] + result["dirty_hits"]) / attempts
        if attempts else 0.0)
    for suffix in ("lease_requests", "lease_grants", "lease_denials",
                   "lease_releases", "opening_leases", "closing_leases",
                   "transfer_flits", "reclaim_requests", "reclaim_releases"):
        result[suffix] = sum(value for name, value in stats.items()
                            if ".srfd_" in name and name.endswith("." + suffix))
    if result["opening_leases"] + result["lease_grants"] != (
            result["lease_releases"] + result["closing_leases"]):
        raise ValueError("SRFD directional lease accounting is unbalanced")
    result["directional_hits"] = sum(value for name, value in stats.items()
        if ".srfd_" in name and ".srfd_Local_" not in name and
        (name.endswith(".clean_hits") or name.endswith(".dirty_hits")))

    # RubySystem-wide timing/reuse statistics were added after the original
    # SRFD runs. Keep old result files readable while exposing the new fields
    # whenever the producing binary supports them.
    global_stats = {
        "hit_interval_samples": "srfd_hit_interval_cycles::samples",
        "mean_cycles_between_hits": "srfd_hit_interval_cycles::mean",
        "hit_residence_samples": "srfd_hit_residence_cycles::samples",
        "mean_store_to_hit_cycles": "srfd_hit_residence_cycles::mean",
        "eviction_events": "srfd_eviction_events",
        "eviction_timestamp_overwrites":
            "srfd_eviction_timestamp_overwrites",
        "evicted_rereferences": "srfd_evicted_rereferences",
        "evicted_rereference_samples":
            "srfd_evicted_rereference_cycles::samples",
        "mean_eviction_to_rereference_cycles":
            "srfd_evicted_rereference_cycles::mean",
        "eviction_addresses_tracked": "srfd_eviction_addresses_tracked",
    }
    for field, suffix in global_stats.items():
        value = stats.get("system.ruby." + suffix, 0.0)
        result[field] = value if np.isfinite(value) else 0.0
    has_global_timing = any(
        name.startswith("system.ruby.srfd_hit_") or
        name.startswith("system.ruby.srfd_eviction_") or
        name.startswith("system.ruby.srfd_evicted_")
        for name in stats)
    if has_global_timing:
        hits = result["clean_hits"] + result["dirty_hits"]
        if result["hit_residence_samples"] != hits:
            raise ValueError("SRFD hit-residence sample accounting is unbalanced")
        if result["hit_interval_samples"] != max(0, hits - 1):
            raise ValueError("SRFD hit-interval sample accounting is unbalanced")
        if (result["evicted_rereferences"] !=
                result["evicted_rereference_samples"]):
            raise ValueError(
                "SRFD eviction re-reference sample accounting is unbalanced")
        if result["eviction_events"] != (
                result["evicted_rereferences"] +
                result["eviction_addresses_tracked"] +
                result["eviction_timestamp_overwrites"]):
            raise ValueError("SRFD eviction lifetime accounting is unbalanced")
    if mode == "baseline" and any(result[name] for name in suffixes):
        raise ValueError("Baseline contains nonzero SRFD actions")
    return result


def validate_srfd_accounting(srfd, paper, context):
    precise = paper.get("opening_dirty_replies") is not None
    for kind in ("dirty", "clean"):
        hits = srfd[kind + "_hits"]
        sent = paper[f"can_put_{kind}_sent"]
        accepted = paper[f"can_put_{kind}_accepted"]
        samples = paper[kind + "_local_count"]
        if precise:
            if (paper[f"opening_{kind}_replies"] + hits !=
                    sent + paper[f"{kind}_replies_pending"]):
                raise ValueError(f"{context}: {kind} reply lifecycle mismatch")
            if (paper[f"opening_{kind}_can_puts"] + sent !=
                    accepted + paper[f"{kind}_can_puts_pending"]):
                raise ValueError(f"{context}: {kind} CAN_PUT lifecycle mismatch")
        elif sent > hits or accepted > sent:
            raise ValueError(f"{context}: legacy {kind} lifecycle counters inconsistent")
        # A reply crossing reset has no ROI miss-start timestamp.
        if samples > sent or sent - samples > paper["untracked_completions"]:
            raise ValueError(f"{context}: {kind} local completion accounting mismatch")
    paper["lifecycle_accounting_verified"] = precise
    untracked_local = sum(paper[f"can_put_{kind}_sent"] - paper[f"{kind}_local_count"]
                          for kind in ("dirty", "clean"))
    if untracked_local > paper["untracked_completions"]:
        raise ValueError(f"{context}: too many untracked local completions")


def _sum_suffix(stats, suffix, description, allow_zero=True):
    values = [value for name, value in stats.items() if name.endswith(suffix)]
    if not values or any(not np.isfinite(value) for value in values):
        raise ValueError(f"Missing or invalid {description}: *{suffix}")
    total = sum(values)
    if not allow_zero and total <= 0:
        raise ValueError(f"{description} must be positive")
    return total


def aggregate_paper_metrics(stats):
    result = {}
    fields = {
        "combined_cycles": ".m_llc_miss_total_cycles",
        "combined_count": ".m_llc_miss_count",
        "memory_cycles": ".m_llc_miss_memory_total_cycles",
        "memory_count": ".m_llc_miss_memory_count",
        "dirty_local_cycles": ".m_llc_miss_dirty_local_total_cycles",
        "dirty_local_count": ".m_llc_miss_dirty_local_count",
        "clean_local_cycles": ".m_llc_miss_clean_local_total_cycles",
        "clean_local_count": ".m_llc_miss_clean_local_count",
        "untracked_completions": ".m_llc_miss_untracked_completions",
        "clean_candidates": ".m_srfd_clean_candidates",
        "clean_emitted": ".m_srfd_clean_emitted",
        "can_put_dirty_sent": ".m_srfd_can_put_dirty_sent",
        "can_put_clean_sent": ".m_srfd_can_put_clean_sent",
        "can_put_dirty_accepted": ".srfd_can_put_dirty_accepted",
        "can_put_clean_accepted": ".srfd_can_put_clean_accepted",
    }
    for field, suffix in fields.items():
        result[field] = _sum_suffix(stats, suffix, field)
    for kind in ("dirty", "clean"):
        for suffix in (f"opening_{kind}_replies", f"{kind}_replies_pending",
                       f"opening_{kind}_can_puts", f"{kind}_can_puts_pending"):
            name = "system.ruby.srfd_" + suffix
            result[suffix] = stats.get(name)
    lifecycle = [result[suffix] for kind in ("dirty", "clean")
                 for suffix in (f"opening_{kind}_replies", f"{kind}_replies_pending",
                                f"opening_{kind}_can_puts", f"{kind}_can_puts_pending")]
    if any(value is not None for value in lifecycle) and any(
            value is None or not np.isfinite(value) or value < 0 for value in lifecycle):
        raise ValueError("Missing or invalid SRFD lifecycle boundary gauge")
    result["combined_samples_available"] = result["combined_count"] > 0
    source_count = result["memory_count"] + result["dirty_local_count"] + result["clean_local_count"]
    source_cycles = result["memory_cycles"] + result["dirty_local_cycles"] + result["clean_local_cycles"]
    if source_count != result["combined_count"] or source_cycles != result["combined_cycles"]:
        raise ValueError("LLC miss-penalty source accounting is unbalanced")
    result["combined_mean_cycles"] = (result["combined_cycles"] / result["combined_count"]
                                      if result["combined_count"] else 0.0)
    result["memory_mean_cycles"] = result["memory_cycles"] / result["memory_count"] if result["memory_count"] else 0.0
    result["dirty_local_mean_cycles"] = result["dirty_local_cycles"] / result["dirty_local_count"] if result["dirty_local_count"] else 0.0
    result["clean_local_mean_cycles"] = result["clean_local_cycles"] / result["clean_local_count"] if result["clean_local_count"] else 0.0
    result["processor_wait_cycles"] = _sum_suffix(stats, ".external_miss_wait_cycles", "processor external-miss wait cycles")
    result["message_stall_ticks"] = _network_stall_ticks(stats)
    return result


def plot_data(results_dir, target_benchmarks, mode="baseline"):
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
        paper = aggregate_paper_metrics(stats)
        llc_miss = paper["combined_mean_cycles"]
        srfd = aggregate_srfd(stats, mode)
        validate_srfd_accounting(srfd, paper, bench)
        system_ipc = _system_ipc(stats)
        throughput = _throughput_metrics(stats)
        network_latency = require_stat(stats, "system.ruby.network.average_packet_latency")
        stall_ticks = paper["message_stall_ticks"]
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
                "histogram_overflows": data["histogram_overflows"],
                "histogram_overflow_percentage": data["histogram_overflow_percentage"],
                "tracked_addresses": int(data["tracked_addresses"]),
                "vc_mean_free_percentage": vc_availability,
                "vc_all_free_percentage": aggregate_vc_availability(stats, all_free=True),
                "llc_miss_penalty_cycles": llc_miss,
                "system_ipc": system_ipc,
                **throughput,
                "network_packet_latency": network_latency,
                "message_stall_ticks": stall_ticks,
                **paper,
                **srfd,
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
    plt.title("Mean Re-Reference Interval by Cache Level")
    plt.ylabel("Cache cycles")
    plt.xticks(x_positions, benchmarks, rotation=45)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{results_dir}/re_reference_cycles.png")
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, vc_avail_data, color="lightgreen", edgecolor="black")
    plt.title("Mean Percentage of Free VCs at Local Input Ports")
    plt.ylabel("Percentage (%)")
    plt.ylim(0, 100)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/vc_availability.png")
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.bar(benchmarks, llc_miss_data, color="salmon", edgecolor="black")
    plt.title("Global LLC Completion Latency")
    plt.ylabel("Cycles")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{results_dir}/llc_miss_penalty.png")
    plt.close()

    print(f"[+] Wrote {csv_path} and three plots.")


def _throughput_metrics(stats):
    """Return guest throughput, host simulation rate, and active-core IPC."""
    sim_ticks = require_stat(stats, "simTicks")
    sim_insts = require_stat(stats, "simInsts")
    sim_ops = require_stat(stats, "simOps")
    host_inst_rate = require_stat(stats, "hostInstRate")
    host_op_rate = require_stat(stats, "hostOpRate")
    if min(sim_ticks, sim_insts, sim_ops, host_inst_rate, host_op_rate) <= 0:
        raise ValueError("Throughput statistics must be positive")

    ipc_pattern = re.compile(r"system\.(switch_cpus|cpu)\d+\.ipc$")
    ipc_groups = {"switch_cpus": [], "cpu": []}
    for name, ipc in stats.items():
        match = ipc_pattern.fullmatch(name)
        if not match or not np.isfinite(ipc):
            continue
        prefix = name[:-len(".ipc")]
        cycles = stats.get(prefix + ".numCycles")
        if cycles is not None and np.isfinite(cycles) and cycles > 0:
            ipc_groups[match.group(1)].append(ipc)

    # With fast-forward, system.cpu* is switched out before the measured
    # region and reports zero cycles/NaN IPC. system.switch_cpus* is active.
    active_ipcs = ipc_groups["switch_cpus"] or ipc_groups["cpu"]
    if not active_ipcs:
        raise ValueError("No finite IPC values from active CPU objects")

    return {
        "sim_insts_per_tick": sim_insts / sim_ticks,
        "sim_ops_per_tick": sim_ops / sim_ticks,
        "host_inst_rate": host_inst_rate,
        "host_op_rate": host_op_rate,
        "average_core_ipc": sum(active_ipcs) / len(active_ipcs),
        "active_ipc_core_count": len(active_ipcs),
    }


def _system_ipc(stats):
    """Measured aggregate IPC, derived from finite system throughput stats."""
    instructions = require_stat(stats, "simInsts")
    seconds = require_stat(stats, "simSeconds")
    if instructions <= 0 or seconds <= 0:
        raise ValueError("Invalid measured system throughput statistics")
    return instructions / (seconds * 2.0e9)  # configured CPU/system clock is 2 GHz


def _network_stall_ticks(stats):
    """Ruby message-buffer stall time (a reproducible network-stall proxy)."""
    values = [value for name, value in stats.items()
              if name.startswith("system.ruby.") and name.endswith(".m_stall_time")]
    if not values:
        raise ValueError("Missing Ruby message-buffer stall-time statistics")
    return sum(values)


def _gmean(values):
    if not values or any(value <= 0 or not np.isfinite(value) for value in values):
        raise ValueError("Cannot calculate geometric mean from invalid values")
    return float(np.exp(np.mean(np.log(values))))


def _mode_stats(results_dir, profile, mode, benchmarks):
    mode_dir = os.path.join(results_dir, profile, mode)
    status_path = os.path.join(mode_dir, "run_status.csv")
    if not os.path.isfile(status_path):
        raise FileNotFoundError(f"Missing completion record for {mode}: {status_path}")
    with open(status_path, newline="", encoding="utf-8") as status_file:
        status = {row["benchmark"]: row for row in csv.DictReader(status_file)}
    output = {}
    for benchmark in benchmarks:
        row = status.get(benchmark)
        if row is None or row.get("status") != "ok":
            detail = "no status" if row is None else row.get("error", "failed")
            raise ValueError(f"{mode}/{benchmark} is not successful: {detail}")
        stats_path = os.path.join(mode_dir, f"{benchmark}_stats.txt")
        if not os.path.isfile(stats_path):
            raise FileNotFoundError(f"Missing statistics for {mode}/{benchmark}")
        output[benchmark] = parse_stats(stats_path)
        run_dir = os.path.join(mode_dir, f"{benchmark}_m5out")
        with open(os.path.join(run_dir, "roi_status.json"), encoding="utf-8") as source:
            roi = json.load(source)
        counts = roi.get("phases", {}).get("roi", {}).get("instructions", [])
        requested = roi.get("phases", {}).get("roi", {}).get("requested_instructions", 0)
        validate_roi(run_dir, len(counts), requested)
        output[benchmark]["srfd_roi_cores"] = len(counts)
        output[benchmark]["srfd_roi_instructions"] = requested
        for phase in ("fast_forward", "warmup"):
            output[benchmark]["srfd_" + phase + "_instructions"] = roi.get(
                "phases", {}).get(phase, {}).get("requested_instructions", 0)
    return output


def plot_paper_comparison(results_dir, target_benchmarks, modes, profile):
    """Compare corrected paper-specific counters against a fresh baseline."""
    if "baseline" not in modes:
        raise ValueError("--compare requires baseline in --srfd-modes")
    benchmarks = list(target_benchmarks)
    all_stats = {mode: _mode_stats(results_dir, profile, mode, benchmarks)
                 for mode in modes}
    labels = {"baseline": "Baseline", "db-defensive": "DB-Defensive",
              "db-aggressive": "DB-Aggressive", "cbdb-defensive": "CB+DB-Defensive",
              "cbdb-aggressive": "CB+DB-Aggressive", "cbdb-nocorner": "CB+DB-NoCorner"}
    parsed = {}
    for mode in modes:
        parsed[mode] = {}
        for bench in benchmarks:
            values = all_stats[mode][bench]
            paper = aggregate_paper_metrics(values)
            srfd = aggregate_srfd(values, mode)
            validate_srfd_accounting(srfd, paper, f"{mode}/{bench}")
            throughput = _throughput_metrics(values)
            parsed[mode][bench] = {
                "llc_miss_penalty": paper["combined_mean_cycles"],
                "processor_wait_cycles": paper["processor_wait_cycles"],
                "sim_ticks": require_stat(values, "simTicks"),
                "sim_insts": require_stat(values, "simInsts"),
                "message_stall_ticks": paper["message_stall_ticks"],
                **throughput,
            }
            if parsed[mode][bench]["sim_ticks"] <= 0 or parsed[mode][bench]["sim_insts"] <= 0:
                raise ValueError(f"Invalid completion statistics for {mode}/{bench}")

    ratios = {name: {} for name in (
        "llc_miss_penalty", "processor_wait_cycles", "tick_speedup",
        "throughput_speedup", "sim_ops_throughput", "host_inst_rate",
        "host_op_rate", "average_core_ipc")}
    rows = []
    for mode in modes:
        for metric in ratios:
            values = []
            for bench in benchmarks:
                base = parsed["baseline"][bench]
                cur = parsed[mode][bench]
                base_stats, cur_stats = all_stats["baseline"][bench], all_stats[mode][bench]
                for key in ("srfd_roi_cores", "srfd_roi_instructions",
                            "srfd_fast_forward_instructions", "srfd_warmup_instructions"):
                    if cur_stats[key] != base_stats[key]:
                        raise ValueError(f"Unequal measurement windows for {mode}/{bench}")
                if metric == "llc_miss_penalty":
                    raw, baseline_value = cur[metric], base[metric]
                    ratio = raw / baseline_value
                elif metric == "processor_wait_cycles":
                    raw, baseline_value = cur[metric], base[metric]
                    ratio = raw / baseline_value
                elif metric == "tick_speedup":
                    raw, baseline_value = cur["sim_ticks"], base["sim_ticks"]
                    ratio = baseline_value / raw
                else:
                    stat_name = {
                        "throughput_speedup": "sim_insts_per_tick",
                        "sim_ops_throughput": "sim_ops_per_tick",
                        "host_inst_rate": "host_inst_rate",
                        "host_op_rate": "host_op_rate",
                        "average_core_ipc": "average_core_ipc",
                    }[metric]
                    raw = cur[stat_name]
                    baseline_value = base[stat_name]
                    ratio = raw / baseline_value
                if baseline_value <= 0 or raw <= 0 or not np.isfinite(ratio):
                    raise ValueError(f"Invalid {metric} for {mode}/{bench}")
                values.append(ratio)
                rows.append({
                    "benchmark": bench, "mode": mode, "metric": metric,
                    "raw_value": raw, "baseline_value": baseline_value,
                    "normalised_to_baseline": ratio,
                    "sim_insts": cur["sim_insts"],
                    "baseline_sim_insts": base["sim_insts"],
                    "instruction_difference": cur["sim_insts"] - base["sim_insts"],
                    "message_stall_ticks": cur["message_stall_ticks"],
                    "sim_insts_per_tick": cur["sim_insts_per_tick"],
                    "sim_ops_per_tick": cur["sim_ops_per_tick"],
                    "host_inst_rate": cur["host_inst_rate"],
                    "host_op_rate": cur["host_op_rate"],
                    "average_core_ipc": cur["average_core_ipc"],
                    "active_ipc_core_count": cur["active_ipc_core_count"],
                })
            ratios[metric][mode] = values + [_gmean(values)]

    out_dir = os.path.join(results_dir, profile)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "paper_style_summary.csv"), "w", newline="", encoding="utf-8") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    titles = {
        "llc_miss_penalty": "Normalised Global LLC Transaction Completion Latency\nLower is better",
        "processor_wait_cycles": "Normalised Sum of Sequencer External-Request Latencies\nLower is better",
        "tick_speedup": "Equal-Work Makespan Speedup (baseline ticks / mode ticks)\nHigher is better",
        "throughput_speedup": "Aggregate-Throughput Speedup\nHigher is better",
        "sim_ops_throughput": "Simulated Micro-op Throughput\nHigher is better",
        "host_inst_rate": "Host Instruction Simulation Rate\nHigher is faster simulation, not guest performance",
        "host_op_rate": "Host Micro-op Simulation Rate\nHigher is faster simulation, not guest performance",
        "average_core_ipc": "Arithmetic Mean IPC of Active Cores\nHigher is better",
    }
    categories = benchmarks + ["Geomean"]
    x = np.arange(len(categories))
    width = min(0.18, 0.8 / len(modes))
    offsets = (np.arange(len(modes)) - (len(modes) - 1) / 2) * width

    def draw(axis, metric):
        axis.axhline(1, color="black", linewidth=0.8)
        for index, mode in enumerate(modes):
            axis.bar(x + offsets[index], ratios[metric][mode], width, label=labels[mode])
        axis.set_ylabel(titles[metric])
        axis.set_xticks(x, categories, rotation=30, ha="right")
        axis.grid(axis="y", alpha=0.25)

    for metric in ratios:
        figure, axis = plt.subplots(figsize=(10, 5))
        draw(axis, metric)
        axis.legend(ncol=2, fontsize="small")
        figure.tight_layout()
        figure.savefig(os.path.join(out_dir, f"paper_{metric}.png"), dpi=180)
        plt.close(figure)
    figure, axes = plt.subplots(
        len(ratios), 1, figsize=(12, 4.5 * len(ratios)), sharex=True)
    for axis, metric in zip(axes, ratios):
        draw(axis, metric)
    axes[0].legend(ncol=2, fontsize="small")
    axes[-1].set_xlabel("SPEC CPU2017 workloads")
    figure.tight_layout()
    figure.savefig(os.path.join(out_dir, "paper_performance_comparison.png"), dpi=180)
    plt.close(figure)
    print(f"[+] Wrote corrected paper comparison CSV and plots to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baseline Evaluation Framework")
    parser.add_argument("--run", action="store_true", help="Run the gem5 benchmarks and collect data")
    parser.add_argument("--plot", action="store_true", help="Parse stats and generate plots")
    parser.add_argument("--compare", action="store_true", help="Generate paper-style cross-mode comparison plots")
    parser.add_argument("--results-dir", type=str, default=f"{GEM5_DIR}/results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}", help="Directory to save/read results")
    parser.add_argument("--benchmark", type=str, help="Comma-separated list of specific benchmarks to run (e.g. omnetpp,namd). Defaults to all active benchmarks.")
    parser.add_argument(
        "--srfd-modes", default="baseline",
        help=("Comma-separated SRFD modes, or 'all' for baseline plus every "
              "SRFD variant"))
    parser.add_argument("--srfd-reserved-vcs", type=int, default=0,
                        help="Data VCs excluded from retained SRFD storage")
    parser.add_argument(
        "--profile",
        choices=("development", "corners-4x4", "corners-4x4-6vc", "paper",
                 "paper-6vc", "paper-mesh-6vc"),
        default="corners-4x4",
    )
    parser.add_argument("--jobs", type=int, default=1,
                        help="Concurrent independent gem5 benchmark runs")
    parser.add_argument("--memory", default="32GB",
                        help="Simulated physical memory size")
    parser.add_argument(
        "--cpu-type", default="X86O3CPU",
        choices=("TimingSimpleCPU", "X86O3CPU"),
        help="Measured-region CPU model (default: X86O3CPU)")
    parser.add_argument(
        "--fast-forward", type=int,
        help="Override fast-forward on every CPU, including benchmark defaults")
    parser.add_argument("--maxinsts", type=int, default=10000000,
                        help="Measured instructions per CPU")
    parser.add_argument("--warmup-insts", type=int, default=100000,
                        help="Timing warmup instructions per CPU before measurement")
    parser.add_argument(
        "--namd-iterations", type=int,
        help=("Override NAMD's --iterations value. Use a value greater than "
              "one for long O3 measurement windows."))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least one")
    if args.maxinsts < 1:
        parser.error("--maxinsts must be positive")
    if args.warmup_insts < 0:
        parser.error("--warmup-insts must be non-negative")
    if args.fast_forward is not None and args.fast_forward < 0:
        parser.error("--fast-forward must be non-negative")
    if args.namd_iterations is not None and args.namd_iterations < 1:
        parser.error("--namd-iterations must be positive")

    if not args.run and not args.plot and not args.compare:
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

    if args.namd_iterations is not None and "namd" in target_benchmarks:
        # Copy the entry so this run-specific override does not mutate the
        # global benchmark catalogue or affect subsequent in-process uses.
        namd_config = dict(target_benchmarks["namd"])
        namd_config["input_flag"] = re.sub(
            r"--iterations\s+\d+",
            f"--iterations {args.namd_iterations}",
            namd_config["input_flag"],
        )
        target_benchmarks = dict(target_benchmarks)
        target_benchmarks["namd"] = namd_config

    valid = (
        "baseline", "db-defensive", "db-aggressive", "cbdb-defensive",
        "cbdb-aggressive", "cbdb-nocorner",
    )
    modes = [m.strip() for m in args.srfd_modes.split(",") if m.strip()]
    if modes == ["all"]:
        modes = list(valid)
    if not modes or set(modes) - set(valid) or len(set(modes)) != len(modes):
        parser.error("Unknown or empty SRFD mode list")

    completed_benchmarks = target_benchmarks
    failed_runs = False
    if args.run:
        completed_benchmarks = {}
        for mode in modes:
            mode_dir = os.path.join(args.results_dir, args.profile, mode)
            mode_completed = (
                run_benchmarks_parallel(
                    mode_dir, target_benchmarks, mode, args.profile,
                    args.jobs, args.memory, args.fast_forward, args.maxinsts,
                    args.cpu_type, args.warmup_insts, args.srfd_reserved_vcs
                ) if args.jobs > 1 else run_benchmarks(
                    mode_dir, target_benchmarks, mode, args.profile,
                    memory=args.memory, fast_forward=args.fast_forward,
                    maxinsts=args.maxinsts, cpu_type=args.cpu_type,
                    warmup_insts=args.warmup_insts,
                    srfd_reserved_vcs=args.srfd_reserved_vcs
                )
            )
            completed_benchmarks.update(mode_completed)
            failed_runs |= set(mode_completed) != set(target_benchmarks)
        
    if args.plot:
        if not os.path.exists(args.results_dir):
            print(f"[-] Error: Results directory {args.results_dir} does not exist. Cannot plot.")
            exit(1)
        if not completed_benchmarks:
            raise RuntimeError("No benchmarks completed successfully; nothing to plot")
        if len(modes) != 1:
            raise ValueError("--plot requires exactly one SRFD mode")
        plot_data(os.path.join(args.results_dir, args.profile, modes[0]),
                  completed_benchmarks, modes[0])
    if args.compare:
        plot_paper_comparison(args.results_dir, target_benchmarks, modes, args.profile)
    if failed_runs:
        raise SystemExit("One or more simulations failed; inspect run_status.csv")
