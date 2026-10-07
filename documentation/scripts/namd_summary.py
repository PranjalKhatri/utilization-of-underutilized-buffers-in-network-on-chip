#!/usr/bin/env python3
"""Print comparable NAMD fields from a results.json or analysis.json file."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("json_file", type=Path)
args = parser.parse_args()
data = json.loads(args.json_file.read_text())
rows = data if isinstance(data, list) else [data]

header = (
    "mode", "cap", "IPC", "LLC cycles", "hit rate", "pressure attempts",
    "pressure releases", "clean hits", "dirty hits"
)
print(" | ".join(header))
print(" | ".join("---" for _ in header))
for row in rows:
    srfd = row.get("srfd", {})
    values = (
        str(row.get("mode", "unknown")),
        str(row.get("storage_limit", "-")),
        f"{row.get('aggregate_ipc', 0):.6f}",
        f"{row.get('llc_completion_mean_cycles', 0):.6f}",
        f"{srfd.get('local_reply_rate_percentage', row.get('local_reply_rate_percentage', 0)):.6f}%",
        f"{srfd.get('pressure_attempts', 0):,.0f}",
        f"{srfd.get('pressure_events', 0):,.0f}",
        f"{srfd.get('clean_hits', row.get('clean_hits', 0)):,.0f}",
        f"{srfd.get('dirty_hits', row.get('dirty_hits', 0)):,.0f}",
    )
    print(" | ".join(values))
