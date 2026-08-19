import os
import re
import subprocess
import matplotlib.pyplot as plt

# Simulation parameters
GEM5_BIN = "./build/NULL/gem5.opt"
CONFIG_SCRIPT = "configs/example/garnet_synth_traffic.py"
STATS_FILE = "m5out/stats.txt"
SIM_CYCLES = 20000
INJECTION_RATE = "0.02"

# Available synthetic traffic patterns in Garnet
traffic_patterns = [
    "uniform_random",
    "tornado",
    "bit_complement",
    "bit_reverse",
    "bit_rotation",
    "neighbor",
    "shuffle",
    "transpose",
]

apl_results = []
valid_patterns = []

for pattern in traffic_patterns:
    cmd = [
        GEM5_BIN,
        CONFIG_SCRIPT,
        "--network=garnet",
        "--num-cpus=16",
        "--num-dirs=16",
        "--topology=Mesh_XY",
        "--mesh-rows=4",
        f"--synthetic={pattern}",
        f"--injectionrate={INJECTION_RATE}",
        "--vcs-per-vnet=4",
        f"--sim-cycles={SIM_CYCLES}",
    ]

    print(f"Running simulation for pattern: {pattern}...", flush=True)
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
        valid_patterns.append(pattern)
        apl_results.append(latency)
        print(f"  -> APL: {latency:.2f} cycles")
    else:
        print(f"  -> Failed to parse stats for {pattern}")

# Plotting the Bar Graph
plt.figure(figsize=(10, 6))
bars = plt.bar(valid_patterns, apl_results, color="teal", edgecolor="black", width=0.6)

# Add value labels above each bar
for bar in bars:
    height = bar.get_height()
    plt.text(
        bar.get_x() + bar.get_width() / 2.0,
        height,
        f"{height:.2f}",
        ha="center",
        va="bottom",
        fontsize=9,
    )

plt.title(
    f"Average Packet Latency (APL) Across Traffic Patterns\n(Mesh_XY, Inj Rate: {INJECTION_RATE}, 16 Nodes)",
    fontsize=12,
)
plt.xlabel("Traffic Pattern", fontsize=11)
plt.ylabel("Average Packet Latency (cycles)", fontsize=11)
plt.xticks(rotation=30, ha="right")
plt.grid(axis="y", linestyle="--", alpha=0.7)
plt.tight_layout()

# Save the plot
plt.savefig("apl_traffic_patterns.png", dpi=300)
print("\nBar graph saved as apl_traffic_patterns.png")