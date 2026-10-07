#!/usr/bin/env python3
"""Generate the figures used by the 4x4 mid-evaluation slides."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


OUT = Path(__file__).resolve().parent
BENCHMARKS = ["Leela", "NAMD", "Cactus"]
COLORS = {
    "baseline": "#8A94A6",
    "db": "#D97706",
    "cbdb": "#3A7D44",
    "clean": "#4C9F70",
    "dirty": "#163A63",
}


def finish(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.png", dpi=240, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def llc_penalty():
    baseline = np.ones(3)
    # NAMD is the checkpointed computation-only 20M-instruction/core ROI.
    cbdb_aggressive = np.array([0.994447, 159.588788 / 166.540087,
                                0.981269])
    x = np.arange(3)
    width = 0.35
    fig, ax = plt.subplots(figsize=(7.2, 4.1))
    ax.bar(x - width / 2, baseline, width, label="Baseline",
           color=COLORS["baseline"])
    bars = ax.bar(x + width / 2, cbdb_aggressive, width,
                  label="CB+DB Aggressive", color=COLORS["cbdb"])
    for bar, value in zip(bars, cbdb_aggressive):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.0007,
                f"{(1-value)*100:.2f}% lower", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.axhline(1.0, color="#374151", linewidth=0.8)
    ax.set_ylim(0.95, 1.006)
    ax.set_xticks(x, BENCHMARKS)
    ax.set_ylabel("Mean LLC miss penalty / baseline")
    ax.set_title("Normalized LLC Miss Penalty (4x4)")
    ax.legend(frameon=False, loc="lower left")
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "srfd_4x4_llc_penalty")


def occupancy():
    # NAMD is the checkpointed computation-only 20M-instruction/core ROI.
    db_aggressive = np.array([4.884, 4.302, 4.883])
    cbdb_aggressive = np.array([4.944, 4.937, 4.936])
    x = np.arange(3)
    width = 0.35
    fig, ax = plt.subplots(figsize=(5.4, 4.1))
    ax.bar(x - width / 2, db_aggressive, width, label="DB Aggressive",
           color=COLORS["db"])
    ax.bar(x + width / 2, cbdb_aggressive, width,
           label="CB+DB Aggressive", color=COLORS["cbdb"])
    ax.axhline(6, color="#374151", linestyle="--", linewidth=1.2,
               label="Six-VC capacity")
    ax.set_ylim(0, 6.5)
    ax.set_xticks(x, BENCHMARKS)
    ax.set_ylabel("Average stored blocks")
    ax.set_title("SRFD Occupancy")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "srfd_4x4_occupancy")


def local_replies():
    # NAMD is the checkpointed computation-only 20M-instruction/core ROI.
    dirty = np.array([18, 5067, 204])
    clean = np.array([93, 5429, 821])
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(5.4, 4.1))
    ax.bar(x, dirty, label="Dirty replies", color=COLORS["dirty"])
    bars = ax.bar(x, clean, bottom=dirty, label="Clean replies",
                  color=COLORS["clean"])
    for i, total in enumerate(dirty + clean):
        ax.text(i, total + 180, f"{total:,}", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.set_ylim(0, 12000)
    ax.set_xticks(x, BENCHMARKS)
    ax.set_ylabel("Successful local replies")
    ax.set_title("CB+DB Aggressive Local Replies")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "srfd_4x4_local_replies")


def hit_rate_trend():
    policies = ["DB-Agg\ncap 6", "CB+DB-Agg\ncap 6",
                "CB+DB-Def\ncap 4", "CB+DB-Agg\ncap 4"]
    rates = np.array([5.5341, 4.1447, 1.6742, 3.0037])
    x = np.arange(len(policies))
    fig, ax = plt.subplots(figsize=(5.6, 4.1))
    bars = ax.bar(x, rates, color=[COLORS["db"], COLORS["cbdb"],
                                  "#75A987", COLORS["cbdb"]])
    for bar, value in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.08,
                f"{value:.2f}%", ha="center", va="bottom", fontsize=9,
                fontweight="bold")
    ax.set_ylim(0, 6.2)
    ax.set_xticks(x, policies)
    ax.set_ylabel("Local replies / eligible requests (%)")
    ax.set_title("NAMD Computation-Only Local Reply Rate")
    ax.grid(axis="y", which="both", alpha=0.22)
    finish(fig, "srfd_4x4_hit_rate_trend")


def message_buffer_stall():
    labels = ["Baseline", "DB-Agg\ncap 6", "CB+DB-Agg\ncap 6",
              "CB+DB-Agg\ncap 4", "CB+DB-Def\ncap 4"]
    # Sum of Ruby MessageBuffer m_stall_time, normalized per simulated
    # instruction and then to baseline.
    normalized = np.array([1.0, 5.225101, 8.000500, 1.202931, 1.046865])
    fig, ax = plt.subplots(figsize=(7.2, 4.1))
    bars = ax.bar(np.arange(len(labels)), normalized,
                  color=[COLORS["baseline"], COLORS["db"], COLORS["cbdb"],
                         "#58A06A", "#8BC49A"])
    for bar, value in zip(bars, normalized):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.10,
                f"{value:.2f}x", ha="center", va="bottom", fontsize=9,
                fontweight="bold")
    ax.set_ylim(0, 8.8)
    ax.set_xticks(np.arange(len(labels)), labels)
    ax.set_ylabel("MessageBuffer stall ticks/instruction / baseline")
    ax.set_title("NAMD Computation-Only Ruby Buffer Stall Proxy")
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "namd_message_buffer_stall")


if __name__ == "__main__":
    llc_penalty()
    occupancy()
    local_replies()
    hit_rate_trend()
    message_buffer_stall()
