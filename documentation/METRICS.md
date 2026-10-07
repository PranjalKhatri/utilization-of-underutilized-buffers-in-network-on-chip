# Statistics and comparisons

## Processor and simulator throughput

For the current 2GHz runs, one cycle is 500 simulated ticks and one simulated
tick is 1ps. Derive metrics from the ROI `simInsts` and `simTicks`, not the
absolute `finalTick` restored from a checkpoint.

```text
ROI cycles                       = simTicks / 500
aggregate IPC                    = simInsts / ROI cycles
average IPC/core, common interval = aggregate IPC / 16
instructions/simulated tick       = simInsts / simTicks
IPC speedup                      = variant aggregate IPC / baseline aggregate IPC
target-time ratio                = baseline simTicks / variant simTicks
```

A ratio above 1 means an improvement. Instructions/tick and IPC are the same
simulated throughput in different units. The common-interval per-core average
includes the whole ROI; it can differ from averages over only active CPU cycles,
particularly in the older paused-core SE experiment.

FS runs keep all cores active until each reaches target, so instruction totals
and progress of faster cores differ. The target-time ratio is not an identical
work comparison. Compare paired windows from the same checkpoint and report
actual instruction counts. Do not compare input preparation and computation
as if they were the same instruction stream.

`hostInstRate` is simulated instructions per real host second. `hostTickRate`
is simulated ticks per host second, not a host CPU clock frequency. `hostSeconds`
resets at the ROI reset and excludes restore/warmup, while statistics-dump work
can contribute. These metrics measure gem5 execution speed and depend on host
load and concurrent jobs. Host CPU cycles were not collected, so host IPC
cannot be reconstructed from them.

## LLC miss penalty

The reported mean is the weighted completion latency across all LLC banks:

```text
sum(m_llc_miss_total_cycles) / sum(m_llc_miss_count)
```

It measures off-chip GETS/GETX issue at L2 through response arrival at L2,
including memory and local-router replies, in Ruby cycles. Ruby runs at 2GHz
in these experiments. It is not a measurement of O3 processor stalled cycles.
Average bank means must be weighted by their sample counts.

## Clean and dirty hit rates

```text
lookups        = sum(gets_lookups) + sum(getx_lookups)
clean hit rate = 100 * sum(clean_hits) / lookups
dirty hit rate = 100 * sum(dirty_hits) / lookups
```

Both rates use the same eligible-router-lookup denominator. Their sum is the
combined local-reply rate. These are not L1/LLC cache hit rates or percentages
of stored blocks. Baseline SRFD lookup/hit instrumentation is disabled, so its
zero counters do not provide a measured eligible-lookup denominator.

## Storage and pressure

| Counter | Meaning |
|---|---|
| `dirty_offered`, `clean_offered` | Eligible candidate packet headers reaching the local input |
| `dirty_stored`, `clean_stored` | Storage admissions during the ROI, not unique addresses |
| `dirty_bypassed` | Dirty overflow forwarded without retention at the cap |
| `clean_bypassed` | Clean overflow scheduled for discard after packet assembly |
| `dirty_forwarded` | Previously retained dirty blocks released toward memory |
| `clean_dropped` | Previously retained clean blocks discarded |
| `pressure_attempts` | Repeated pressure checks after NI VC allocation failures, across vnets |
| `pressure_events` | Successful pressure-triggered releases of retained blocks |
| `pressure_no_victim` | Checks where the policy found no eligible complete victim |
| `max_stored` | Peak retained occupancy at one input; aggregate using max, not sum |
| `resident`, `opening_resident` | Closing and opening retained-block gauges |

Bypasses are admission decisions, not pressure releases. Ordinary traffic may
occupy reserved capacity temporarily. These counters do not identify how many
CPU stalled cycles were caused by SRFD, and attempts are not unique packets.
Baseline pressure counters are disabled; zero does not establish that baseline
traffic had no VC-allocation failures.

The evaluator checks:

```text
pressure_attempts = pressure_events + pressure_no_victim
offered(kind)     = stored(kind) + bypassed(kind)   [new counter format]
opening_resident + dirty_stored + clean_stored
  = dirty_hits + clean_hits + dirty_forwarded + clean_dropped + resident
```

Reply/CAN_PUT lifecycle checks also account for pending transactions crossing
an ROI reset. Older statistics without bypass counters are treated as zero
bypass and remain readable.

Occupancy is time-weighted over LLC-facing inputs. State its denominator:
retained blocks out of the configured cap, or physical data VCs out of six.
Time with all six stored is different from time at a new four-block cap.
Ordinary VC occupancy is not included in SRFD-only occupancy. Residence means
include released blocks but exclude live survivors; opening entries have
reset-relative ages.

## SRFD hit and post-eviction reuse timing

The RubySystem-wide counters below are reset at the ROI boundary. They provide
sample counts and distribution means directly in Ruby cycles:

| Statistic | Meaning |
|---|---|
| `system.ruby.srfd_hit_interval_cycles` | Cycles between consecutive local SRFD replies anywhere in the system |
| `system.ruby.srfd_hit_residence_cycles` | Cycles from storing a block in SRFD until that same retained copy supplies a local reply |
| `system.ruby.srfd_eviction_events` | Complete retained blocks removed without supplying a local reply |
| `system.ruby.srfd_evicted_rereferences` | First later GETS/GETX references to tracked SRFD-evicted addresses |
| `system.ruby.srfd_evicted_rereference_cycles` | Cycles from the most recent tracked SRFD eviction until that reference |
| `system.ruby.srfd_eviction_timestamp_overwrites` | Same address evicted again before it is referenced; the newer eviction becomes the timing origin |
| `system.ruby.srfd_eviction_addresses_tracked` | Addresses still awaiting a later reference at the end of the interval |

Use the distribution `::mean` and `::samples` fields. The first hit after a
statistics reset has no interval sample, so normally
`hit_interval_cycles::samples = hit_residence_cycles::samples - 1` when at
least one hit occurs. Hits in the same Ruby cycle produce a valid zero-cycle
interval.

The old per-input `residence_cycles` distribution mixes local hits, dirty
pressure forwarding, clean drops, duplicate coalescing and clean-GETX
conflicts. Use `srfd_hit_residence_cycles` for store-to-hit latency.

Post-eviction tracking is cache-line-address based. It records pressure
releases and all other complete SRFD removals that do not supply a local reply.
Only the first later eligible GETS/GETX consumes a timestamp. A block that is
never referenced again remains in `srfd_eviction_addresses_tracked`; it is not
included in the re-reference mean.

Print the principal values from any new stats file with:

```sh
python3 documentation/scripts/srfd_timing.py PATH/roi_stats.txt
```

Injected flits per instruction can describe traffic overhead across windows
with different retired totals. Network packet latency can include intentional
SRFD retention; injected-minus-received also includes dropped packets and must
not be called ordinary congestion without further accounting. No ablation has
yet isolated the exact CPU cost attributable to retention.

The earlier NAMD measurements and formulas are saved in
`PAPER_TESTS/namd_pressure_speed_20261006/REPORT.md` and `metrics.json`.
