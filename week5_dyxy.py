import argparse
import subprocess
import os
import re
import math
import concurrent.futures
import matplotlib.pyplot as plt

# --- Configuration ---
GEM5_CMD = "./build/Garnet_standalone/gem5.opt"
# GEM5_CMD = "./build/NULL/gem5.opt"
CONFIG_SCRIPT = "configs/example/garnet_synth_traffic.py"
OUT_BASE = "m5out/parallel_runs"

routing_algos = {1: "XY", 3: "Odd-Even", 4: "DyXY"}
# traffic_patterns = ["shuffle"]
traffic_patterns = ["uniform_random"]
# traffic_patterns = ["poisson"]
# traffic_patterns = ["tornado", "bit_complement"]
fixed_inj_rate = 0.06 
fixed_nodes = 16
fixed_mesh = 4


def parse_arguments():
    parser = argparse.ArgumentParser(description="gem5 Garnet NoC Simulation and Plotting Script")
    parser.add_argument('--mode', choices=['fast', 'slow'], default='fast',
                        help="Choose 'fast' for quick tests or 'slow' for full paper evaluation.")
    parser.add_argument('--action', choices=['run', 'plot'], default='run',
                        help="'run' executes gem5 and plots. 'plot' only parses existing stats and plots.")
    return parser.parse_args()

def extract_stat(stats_file, stat_name):
    """Parses a specific stats.txt for a stat and returns its float value."""
    if not os.path.exists(stats_file):
        return None
    with open(stats_file, "r") as f:
        for line in f:
            if line.startswith(stat_name):
                try:
                    return float(line.split()[1])
                except (ValueError, IndexError):
                    return None
    return None

def read_simulation_stats(params):
    """Reads stats from a completed simulation directory (used for plot-only mode)."""
    num_nodes, mesh_rows, inj_rate, algo_id, pattern, exp_type = params
    run_name = f"{exp_type}_{pattern}_n{num_nodes}_r{inj_rate}_a{algo_id}"
    stats_file = os.path.join(OUT_BASE, run_name, "stats.txt")
    
    latency = extract_stat(stats_file, "system.ruby.network.average_packet_latency")/1000
    response_time = extract_stat(stats_file, "system.ruby.network.average_packet_queueing_latency")/1000
    
    return params, latency, response_time

def run_simulation(params, total_packets):
    """Executes a gem5 simulation and returns the extracted stats."""
    num_nodes, mesh_rows, inj_rate, algo_id, pattern, exp_type = params
    
    packets_per_node = math.ceil(total_packets / num_nodes)
    # sim_ticks = int(cycles_to_inject + 50000) * 1000

    sim_ticks = 20000000
    # sim_ticks = 1000000
    
    run_name = f"{exp_type}_{pattern}_n{num_nodes}_r{inj_rate}_a{algo_id}"
    outdir = os.path.join(OUT_BASE, run_name)
    stats_file = os.path.join(outdir, "stats.txt")
    
    cmd = [ 
        GEM5_CMD, "-d", outdir, 
        CONFIG_SCRIPT, 
        # "--ruby", 
        # "--ruby-clock=2GHz", 
        # "--sys-clock=2GHz", 
        # "--mem-type=SimpleMemory", 
        "--network=garnet", 
        f"--num-cpus={num_nodes}", 
        f"--num-dirs={num_nodes}", 
        "--topology=Mesh_XY", 
        f"--mesh-rows={int(num_nodes**0.5)}", 
        f"--routing-algorithm={algo_id}", 
        f"--synthetic={pattern}", 
        f"--injectionrate={inj_rate}", 
        # f"--num-packets-max={packets_per_node}",
        # "--inj-vnet=2",
        # "--buffers-per-ctrl-vc=100000",
        # "--buffers-per-data-vc=100000", 
        "--vcs-per-vnet=1", 
        # "--single-dest-id=6",
        f"--num-l2caches={num_nodes}", 
        f"--sim-cycles={sim_ticks}" ]
    
    # result = subprocess.run(cmd, capture_output=True, text=True)
    os.makedirs(outdir, exist_ok=True)

    stdout_file = os.path.join(outdir, "stdout.txt")
    stderr_file = os.path.join(outdir, "stderr.txt")

    with open(stdout_file, "w") as stdout, \
        open(stderr_file, "w") as stderr:

        result = subprocess.run(
            cmd,
            stdout=stdout,
            stderr=stderr,
            text=True
        )
    
    if not os.path.exists(stats_file):
        print(f"\n[!] CRASH DETECTED: {run_name}")
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, "crash_log.txt"), "w") as f:
            f.write("=== STDERR ===\n" + result.stderr)
            f.write("\n=== STDOUT ===\n" + result.stdout)
        return params, None, None

    latency = extract_stat(stats_file, "system.ruby.network.average_packet_latency")/1000
    response_time = extract_stat(stats_file, "system.ruby.network.average_packet_queueing_latency")/1000
    injected_packets = extract_stat(stats_file, "system.ruby.network.packets_injected::total")
    
    if latency is None or response_time is None:
        print(f"\n[!] STAT MISSING: {run_name} finished, but required metrics were not in stats.txt")
        return params, None, None
        
    if injected_packets is not None and injected_packets < (total_packets * 0.99):
        print(f"\n[?] SATURATION WARNING: {run_name} choked! Only injected {int(injected_packets)} / {total_packets} packets.")

    return params, latency, response_time

def plot_results(task_results, mesh_configs, inj_rates):
    """Aggregates parsed results and generates Matplotlib charts."""
    print("\nGenerating graphs...")
    
    results_exp1 = {p: {a: {} for a in routing_algos} for p in traffic_patterns}
    results_lat  = {p: {a: {} for a in routing_algos} for p in traffic_patterns}
    results_resp = {p: {a: {} for a in routing_algos} for p in traffic_patterns}

    # Aggregate data
    for params, lat, resp in task_results:
        nodes, mesh, rate, algo, pattern, exp_type = params
        safe_lat = lat if lat is not None else math.nan
        safe_resp = resp if resp is not None else math.nan
        
        if exp_type == "exp1":
            results_exp1[pattern][algo][nodes] = safe_lat
        else:
            results_lat[pattern][algo][rate] = safe_lat
            results_resp[pattern][algo][rate] = safe_resp

    cores_list = list(mesh_configs.keys())

    # Plotting Phase
    for pattern in traffic_patterns:
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))

        # Graph 1: Latency vs Cores
        for algo, name in routing_algos.items():
            y_data = [results_exp1[pattern][algo].get(c, math.nan) for c in cores_list]
            axes[0].plot(cores_list, y_data, marker='o', label=name)
        axes[0].set_title(f'[{pattern}] Latency vs Cores (Rate={fixed_inj_rate})')
        axes[0].set_xlabel('Number of cores in a NoC (UxV)')
        axes[0].set_ylabel('Average packet latency')
        axes[0].set_xticks(cores_list) 
        axes[0].legend()
        axes[0].grid(True)

        # Graph 2: Latency vs Injection Rate
        for algo, name in routing_algos.items():
            y_data = [results_lat[pattern][algo].get(r, math.nan) for r in inj_rates]
            axes[1].plot(inj_rates, y_data, marker='s', label=name)
        axes[1].set_title(f'[{pattern}] Latency vs Injection Rate')
        axes[1].set_xlabel('Average packet injection rate')
        axes[1].set_ylabel('Average packet latency')
        axes[1].legend()
        axes[1].grid(True)

        # Graph 3: Response Time vs Injection Rate
        for algo, name in routing_algos.items():
            y_data = [results_resp[pattern][algo].get(r, math.nan) for r in inj_rates]
            axes[2].plot(inj_rates, y_data, marker='^', label=name)
        axes[2].set_title(f'[{pattern}] Response Time vs Injection Rate')
        axes[2].set_xlabel('Average packet injection rate')
        axes[2].set_ylabel('Average mean queueing latency')
        axes[2].legend()
        axes[2].grid(True)

        plt.tight_layout()
        filename = f"routing_metrics_{pattern}.png"
        plt.savefig(filename)
        print(f"[!] Saved graph: '{filename}'")
        plt.close()
    # ============================================================
    # Save all statistics to TXT file
    # ============================================================

    stats_filename = "routing_stats.txt"

    with open(stats_filename, "w") as f:

        # ========================================================
        # Experiment 1
        # ========================================================

        f.write("=" * 100 + "\n")
        f.write("EXPERIMENT 1: LATENCY VS NUMBER OF CORES\n")
        f.write("=" * 100 + "\n\n")

        f.write(
            f"{'Traffic Pattern':<20}"
            f"{'Algorithm':<20}"
            f"{'Cores':<12}"
            f"{'Mesh':<12}"
            f"{'Injection Rate':<18}"
            f"{'Average Latency':<20}\n"
        )

        f.write("-" * 100 + "\n")

        for pattern in traffic_patterns:

            for algo, name in routing_algos.items():

                for nodes in cores_list:

                    latency = results_exp1[pattern][algo].get(
                        nodes,
                        math.nan
                    )

                    mesh = mesh_configs.get(nodes, "N/A")

                    f.write(
                        f"{pattern:<20}"
                        f"{name:<20}"
                        f"{nodes:<12}"
                        f"{str(mesh):<12}"
                        f"{fixed_inj_rate:<18}"
                        f"{latency:<20}\n"
                    )

        f.write("\n\n")

        # ========================================================
        # Experiment 2
        # ========================================================

        f.write("=" * 100 + "\n")
        f.write("EXPERIMENT 2: LATENCY VS INJECTION RATE\n")
        f.write("=" * 100 + "\n\n")

        f.write(
            f"{'Traffic Pattern':<20}"
            f"{'Algorithm':<20}"
            f"{'Injection Rate':<18}"
            f"{'Average Latency':<20}\n"
        )

        f.write("-" * 80 + "\n")

        for pattern in traffic_patterns:

            for algo, name in routing_algos.items():

                for rate in inj_rates:

                    latency = results_lat[pattern][algo].get(
                        rate,
                        math.nan
                    )

                    f.write(
                        f"{pattern:<20}"
                        f"{name:<20}"
                        f"{rate:<18}"
                        f"{latency:<20}\n"
                    )

        f.write("\n\n")

        # ========================================================
        # Experiment 3
        # ========================================================

        f.write("=" * 100 + "\n")
        f.write("EXPERIMENT 3: RESPONSE TIME VS INJECTION RATE\n")
        f.write("=" * 100 + "\n\n")

        f.write(
            f"{'Traffic Pattern':<20}"
            f"{'Algorithm':<20}"
            f"{'Injection Rate':<18}"
            f"{'Mean Queueing Latency':<25}\n"
        )

        f.write("-" * 85 + "\n")

        for pattern in traffic_patterns:

            for algo, name in routing_algos.items():

                for rate in inj_rates:

                    response = results_resp[pattern][algo].get(
                        rate,
                        math.nan
                    )

                    f.write(
                        f"{pattern:<20}"
                        f"{name:<20}"
                        f"{rate:<18}"
                        f"{response:<25}\n"
                    )

    print(f"[!] Saved statistics: '{stats_filename}'")

def main():
    args = parse_arguments()

    if args.mode == 'fast':
        print(f"\n[!] MODE: FAST TEST ({args.action.upper()})")
        TOTAL_PACKETS = 250000
        mesh_configs = {4: 2, 16: 4}
        # inj_rates = [ 0.2, 0.4, 0.50, 0.60]
        inj_rates = [ 0.1, 0.2,0.3,0.325]
    else:
        print(f"\n[!] MODE: SLOW FULL EVALUATION ({args.action.upper()})")
        TOTAL_PACKETS = 250000
        mesh_configs = {4: 2, 8: 2, 16: 4, 64: 8}
        inj_rates = [0.01, 0.10, 0.15,0.20,0.25, 0.30,0.35, 0.40,0.45, 0.50]

    # --- Task Generation ---
    tasks = []
    for pattern in traffic_patterns:
        # for nodes, rows in mesh_configs.items():
        #     for algo in routing_algos:
        #         tasks.append((nodes, rows, fixed_inj_rate, algo, pattern, "exp1"))
        for rate in inj_rates:
            for algo in routing_algos:
                tasks.append((fixed_nodes, fixed_mesh, rate, algo, pattern, "exp2"))

    total_tasks = len(tasks)
    task_results = []

    # --- Execution Phase ---
    if args.action == 'run':
        print(f"Executing {total_tasks} simulations in parallel...")
        max_workers = os.cpu_count() or 4
        # max_workers = 1
        completed = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_simulation, task, TOTAL_PACKETS): task for task in tasks}
            
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                params, lat, resp = future.result()
                nodes, mesh, rate, algo, pattern, exp_type = params
                
                if lat is not None and resp is not None:
                    print(f"[{completed}/{total_tasks}] Success: Algo={routing_algos[algo]:<8} | Pattern={pattern[:7]:<7} | Rate={rate:<4} | Nodes={nodes:<3}")
                else:
                    print(f"[{completed}/{total_tasks}] FAILED : Algo={routing_algos[algo]:<8} | Pattern={pattern[:7]:<7} | Rate={rate:<4} | Nodes={nodes:<3}")
                
                task_results.append((params, lat, resp))

    elif args.action == 'plot':
        print(f"Parsing existing stats for {total_tasks} configurations...")
        for task in tasks:
            params, lat, resp = read_simulation_stats(task)
            task_results.append((params, lat, resp))

    # --- Plotting Phase ---
    plot_results(task_results, mesh_configs, inj_rates)

if __name__ == "__main__":
    main()