import os
import re
import subprocess
import matplotlib.pyplot as plt
import numpy as np

# Simulation settings
GEM5_BIN = "./build/NULL/gem5.opt"
CONFIG_SCRIPT = "configs/example/garnet_synth_traffic.py"
STATS_FILE = "m5out/stats.txt"
SIM_CYCLES = 20000

# Sweep injection rate from 0.02 to 0.50 in steps of 0.02
injection_rates = np.arange(0.02, 0.52, 0.02)
apl_results = []
valid_rates = []

for rate in injection_rates:
    rate_str = f"{rate:.2f}"
    
    cmd = [
        GEM5_BIN,
        CONFIG_SCRIPT,
        "--network=garnet",
        "--num-cpus=16",
        "--num-dirs=16",
        "--topology=Mesh_XY",
        "--mesh-rows=4",
        "--synthetic=uniform_random",
        f"--injectionrate={rate_str}",
        "--vcs-per-vnet=4",
        f"--sim-cycles={SIM_CYCLES}",
    ]
    
    print(f"Running simulation for injection rate: {rate_str}...", flush=True)
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Extract average_packet_latency from m5out/stats.txt
    latency = None
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            for line in f:
                if "system.ruby.network.average_packet_latency" in line:
                    match = re.search(r"average_packet_latency\s+([0-9.]+)", line)
                    if match:
                        latency = float(match.group(1))
                        break
                        
    if latency is not None:
        valid_rates.append(rate)
        apl_results.append(latency)
        print(f"  -> APL: {latency:.2f} cycles")
    else:
        print(f"  -> Failed to parse stats for rate {rate_str}")

# Plotting the Latency vs Injection Rate Curve
plt.figure(figsize=(8, 5))
plt.plot(valid_rates, apl_results, marker="o", linestyle="-", color="b", label="Uniform Random (Mesh_XY DOR)")
plt.title("Average Packet Latency (APL) vs Injection Rate")
plt.xlabel("Injection Rate (packets/node/cycle)")
plt.ylabel("Average Packet Latency (cycles)")
plt.grid(True, linestyle="--", alpha=0.7)
plt.legend()
plt.tight_layout()

# Save output graph
plt.savefig("apl_vs_injection_rate.png", dpi=300)
print("\nPlot successfully saved to apl_vs_injection_rate.png")