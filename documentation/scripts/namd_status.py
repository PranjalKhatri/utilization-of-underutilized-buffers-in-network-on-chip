#!/usr/bin/env python3
"""Report the current phase and per-core progress of one NAMD FS run."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()

status_path = args.output / "fs_roi_status.json"
verification_path = args.output / "verification.json"
if not status_path.is_file():
    parser.error(f"missing {status_path}")

status = json.loads(status_path.read_text())
print(f"status: {status.get('status', 'unknown')}")
print(f"cores: {status.get('cores', 'unknown')}")
print(f"mode: {status.get('srfd_mode', 'unknown')}")
if "srfd_storage_limit" in status:
    print(f"storage limit: {status['srfd_storage_limit']} blocks/input")

phase = status.get("active_phase")
if phase:
    counts = phase.get("instructions", [])
    print(f"active phase: {phase.get('name')}")
    if counts:
        print(f"instructions: min={min(counts):,} max={max(counts):,} aggregate={sum(counts):,}")

for name, record in status.get("phases", {}).items():
    counts = record.get("instructions", [])
    if counts:
        print(f"{name}: min={min(counts):,} max={max(counts):,} aggregate={sum(counts):,}")

if status.get("events"):
    print("events:")
    for event in status["events"]:
        print(f"  {event}")

if verification_path.is_file():
    verification = json.loads(verification_path.read_text())
    print(f"verification passed: {verification.get('passed')}")
