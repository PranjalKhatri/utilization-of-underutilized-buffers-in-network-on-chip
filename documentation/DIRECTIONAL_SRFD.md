# Directional SRFD storage

See [ESCAPE_VC_EXPLAINED.md](ESCAPE_VC_EXPLAINED.md) for concrete deadlock and
East-to-North release examples, including physical storage versus logical
routing origin.

Enable with `--srfd-directional-storage`; disable with
`--no-srfd-directional-storage`. The default remains Local-only SRFD.

The extension stores local LLC evictions in existing directional input VCs of
the same router. It preserves MOESI ownership, reply messages and CAN_PUT
processing. It does not move a block into a neighbouring router.

## Capacity and escape routing

Enabled configurations require Garnet, MOESI_CMP_directory, XY routing,
homogeneous router clocks/VC counts and unbridged internal links. At least two
VCs and at least one reserved VC are required.

The highest-numbered VC in each data vnet is an escape VC. Ordinary traffic
cannot allocate it, and SRFD cannot retain blocks there. Local SRFD replies
and dirty blocks released from storage use this VC at every subsequent hop.
They start routing as local injection, irrespective of the physical input
holding the packet. This avoids dependencies between arbitrary directional
storage buffers and ordinary XY channels.

With six physical VCs:

| Flags | Per-input retention cap | Ordinary data VCs | Escape VCs |
|---|---:|---:|---:|
| directional + `--srfd-reserved-vcs=2` | 4 | 5 | 1 |
| directional + `--srfd-reserved-vcs=1` | 5 | 5 | 1 |
| directional + `--srfd-reserved-vcs=0` | Invalid | --- | --- |

The reservation is a retention limit, not a permanently dedicated set of
directional storage VCs. The escape VC counts toward reserved headroom.
Absent corner/edge directions are not allocated. Other controller-facing
Local inputs are not spill destinations.

The 4x4 mesh has 48 directional inputs and 16 LLC-facing Local inputs. Their
theoretical aggregate retention limits are 256 blocks at cap 4 and 320 at
cap 5. Actual storage is constrained by ordinary traffic, leases and packet
draining. Six physical VCs cannot provide cap 6 with this escape design.

## Placement and credits

Local retention is preferred. A complete overflow candidate waits in its
original Local VC while the router tries directional inputs in ascending
retained occupancy, rotating ties. One spill transfer is active per router.
Each direction is tried once; failure falls back to clean drop or dirty
writeback. When Local NI allocation fails, a complete retained Local block
can also migrate, allowing cap 5 to spill even when all ordinary Local VCs
are occupied.

Before transfer, the upstream neighbour grants a lease only if its output
allocation entry is idle with all credits returned and ordinary allocation
has no competing demand in that cycle. The grant masks that entry from
ordinary allocation. This prevents packets already allocated/in flight from
colliding with local storage.

Reservation, grant, reclaim and release use a separate modeled control path
with the internal link latency in each direction. Control callbacks run after
ordinary switch allocation. Lease IDs and reclaim epochs protect ownership
and prevent stale acknowledgements from clearing newer requests.

The transfer takes one flit per cycle, with one transfer per router. It uses
an added internal read/write path; it does not consume inter-router hops.
The model assumes this path can operate alongside the normal input datapath.
Its extra port/control/tag costs must be considered in hardware analysis.

The original Local credits are returned as flits leave that buffer. Borrowed
flits never return ordinary credits to the directional neighbour: that
neighbour did not inject them. Its ordinary credits remain unchanged while
the VC is leased. The lease is released only when the last flit leaves or is
discarded, followed by control-path latency before upstream allocation can
resume.

## Pressure, lookup and ROI boundaries

An upstream router requests reclaim when ordinary VC allocation fails in the
affected vnet. New leases pause while reclaim is pending. The destination
reclaims its oldest complete retained victim even under aggressive policy:
clean victims are dropped and dirty victims drain through the escape path.
One victim is selected per reclaim request. Dirty draining retains the lease
until the tail leaves; reclaim has no fixed completion-time guarantee under
congestion. Ordinary traffic has allocation priority over a subsequent lease.

Router-wide address lookup covers every retained location. Pending-store
markers remain active during transfers; incomplete copies cannot serve hits.
Duplicate handling spans all inputs. Once a hit or release wins, the address
leaves the retained index, preventing a second reply/removal.

Statistics resets preserve runtime leases, reclaim epochs and transfers.
Opening/closing staged-offer and lease gauges account for operations crossing
an ROI boundary. Existing retained ages reset relative to the measurement
start. Transfer preserves the current entry age and replacement order.

## Statistics

Per-input `srfd_DIRECTION_portN` groups add `lease_requests`, `lease_grants`,
`lease_denials`, `lease_releases`, `opening_leases`, `closing_leases`,
`transfer_flits`, `reclaim_requests`, `reclaim_releases` and `reclaim_cycles`.
Directional `clean_hits`/`dirty_hits` identify the successful storage location;
eligible request lookups are still counted at their original Local input.

The evaluator checks lease balance:

```text
opening_leases + lease_grants = lease_releases + closing_leases
```

Staged overflow offers are accounted for with opening/closing per-kind
gauges. Migration is not another admission or eviction. Directional reclaim
counters are separate from Local NI `pressure_attempts`/`pressure_events`.
A delayed failed migration performs a new Local pressure check when it falls
back to release, so it does not rewrite counters from before an ROI reset.

## NAMD comparison

Use the same cold call-7 computation checkpoint and six-VC 4x4 corner topology
as the earlier NAMD measurements. The supported launcher revalidates binary
compatibility with complete baseline KVM execution and native-output checks
before permitting O3 restores.

```sh
docker exec -w /docker_mounted_gem5 gem5_fs_dev \
  python3 documentation/scripts/directional_namd_sweep.py \
  --output=PAPER_TESTS/namd_directional_comparison
```

The workflow validates 2x2 and 4x4 checkpoint restoration, runs short 2x2 O3
smokes, and then serially measures an escape-reserved baseline followed by
CB+DB-aggressive caps 4 and 5. Long runs use 100k warmup and at least 20M ROI
instructions per core. Input preparation is excluded.

Compare against both the matched escape-reserved baseline and the historical
Local-only results, clearly identifying the latter's different available
network capacity. `workflow_status.json`, per-run `fs_roi_status.json`,
`verification.json`, `roi_stats.txt`, `analysis.json` and `results.json` record
progress and results under the supplied ignored output directory.
