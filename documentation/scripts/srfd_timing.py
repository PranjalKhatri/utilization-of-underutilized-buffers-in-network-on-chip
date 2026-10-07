#!/usr/bin/env python3
"""Print the RubySystem-wide SRFD timing/re-reference statistics."""

import argparse
import math
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("stats", type=Path, help="gem5 text statistics file")
args = parser.parse_args()

stats = {}
for line in args.stats.read_text().splitlines():
    fields = line.split()
    if len(fields) < 2:
        continue
    try:
        stats[fields[0]] = float(fields[1])
    except ValueError:
        pass


def value(suffix):
    result = stats.get("system.ruby." + suffix)
    return result if result is not None and math.isfinite(result) else None


def show(label, suffix, integer=False):
    result = value(suffix)
    if result is None:
        rendered = "unavailable"
    elif integer:
        rendered = f"{result:,.0f}"
    else:
        rendered = f"{result:,.3f}"
    print(f"{label}: {rendered}")


show("local replies sampled", "srfd_hit_residence_cycles::samples", True)
show("average store-to-hit cycles", "srfd_hit_residence_cycles::mean")
show("hit intervals sampled", "srfd_hit_interval_cycles::samples", True)
show("average cycles between hits", "srfd_hit_interval_cycles::mean")
show("SRFD eviction events", "srfd_eviction_events", True)
show("re-referenced evicted addresses", "srfd_evicted_rereferences", True)
show("average eviction-to-re-reference cycles",
     "srfd_evicted_rereference_cycles::mean")
show("repeat-eviction timestamp overwrites",
     "srfd_eviction_timestamp_overwrites", True)
show("addresses still tracked", "srfd_eviction_addresses_tracked", True)
