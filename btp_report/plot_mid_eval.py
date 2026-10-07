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
    cbdb_aggressive = np.array([0.994447, 0.986315, 0.981269])
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
    ax.set_ylim(0.97, 1.006)
    ax.set_xticks(x, BENCHMARKS)
    ax.set_ylabel("Mean LLC miss penalty / baseline")
    ax.set_title("Normalized LLC Miss Penalty (4x4, 10M instruction limit)")
    ax.legend(frameon=False, loc="lower left")
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "srfd_4x4_llc_penalty")


def occupancy():
    db_aggressive = np.array([4.884, 4.872, 4.883])
    cbdb_aggressive = np.array([4.944, 4.985, 4.936])
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
    dirty = np.array([18, 17, 204])
    clean = np.array([93, 106, 821])
    x = np.arange(3)
    fig, ax = plt.subplots(figsize=(5.4, 4.1))
    ax.bar(x, dirty, label="Dirty replies", color=COLORS["dirty"])
    bars = ax.bar(x, clean, bottom=dirty, label="Clean replies",
                  color=COLORS["clean"])
    for i, total in enumerate(dirty + clean):
        ax.text(i, total + 18, f"{total:,}", ha="center", va="bottom",
                fontsize=9, fontweight="bold")
    ax.set_ylim(0, 1150)
    ax.set_xticks(x, BENCHMARKS)
    ax.set_ylabel("Successful local replies")
    ax.set_title("CB+DB Aggressive Local Replies")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", alpha=0.22)
    finish(fig, "srfd_4x4_local_replies")


def hit_rate_trend():
    policies = ["DB-Def", "DB-Agg", "CB+DB-Def", "CB+DB-Agg"]
    rates = {
        "Leela": [0.006762, 0.016904, 0.008334, 0.017131],
        "NAMD": [0.018722, 0.064568, 0.046155, 0.102166],
        "Cactus": [0.040559, 0.103358, 0.205858, 0.392636],
    }
    markers = ["o", "s", "^"]
    colors = ["#D97706", "#163A63", "#3A7D44"]
    x = np.arange(len(policies))
    fig, ax = plt.subplots(figsize=(5.6, 4.1))
    for (benchmark, values), marker, color in zip(
            rates.items(), markers, colors):
        ax.plot(x, values, marker=marker, linewidth=2.0, markersize=6,
                label=benchmark, color=color)
    ax.set_yscale("log")
    ax.set_xticks(x, policies, rotation=18, ha="right")
    ax.set_ylabel("Local reply rate (%) — log scale")
    ax.set_title("Useful-Hit Trend by SRFD Policy")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", which="both", alpha=0.22)
    finish(fig, "srfd_4x4_hit_rate_trend")


if __name__ == "__main__":
    llc_penalty()
    occupancy()
    local_replies()
    hit_rate_trend()
