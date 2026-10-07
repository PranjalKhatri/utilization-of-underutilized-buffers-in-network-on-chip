# SRFD and network flags

`--srfd-directional-storage` enables dynamic borrowing from existing cardinal
input buffers. `--no-srfd-directional-storage` disables it; Local-only storage
is the default. Enabled experiments reserve one data escape VC and support
caps 4 and 5 with six physical VCs. See [DIRECTIONAL_SRFD.md](DIRECTIONAL_SRFD.md)
for ownership, pressure behavior, limits and matching baseline requirements.

The direct gem5 flags below are defined in `configs/network/Network.py`.
They are used with MOESI CMP directory and Garnet. `srfd_eval.py` also forwards
`--srfd-reserved-vcs` for its serial and parallel SE benchmark runs.

## Operating modes

`--srfd-mode` defaults to `baseline`.

| Mode | Retained blocks | Release policy after NI VC allocation fails |
|---|---|---|
| `baseline` | None | SRFD disabled |
| `db-defensive` | Dirty | Release the oldest complete block if any is available |
| `db-aggressive` | Dirty | Release the oldest complete block when complete stored occupancy reaches the configured cap |
| `cbdb-defensive` | Clean and dirty | Release the oldest complete block if any is available |
| `cbdb-aggressive` | Clean and dirty | Release the oldest complete block when complete stored occupancy reaches the configured cap |
| `cbdb-nocorner` | Clean and dirty outside corner routers | Aggressive; SRFD is bypassed at the four mesh corners |

`srfd_eval.py` uses the plural `--srfd-modes`, accepting a comma-separated list
or `all`. The gem5 configuration and FS checkpoint launcher use one mode.

Clean retained blocks can satisfy GETS only. Dirty retained blocks can satisfy
GETS or GETX. A clean conflict with GETX discards the stored clean block and
lets the request continue to memory. Released dirty blocks are written back;
released clean blocks are discarded.

## Reserved capacity

`--srfd-reserved-vcs=N` defaults to **0**. It bounds retained SRFD blocks in
each eligible local data input:

```text
retained-block cap = vcs-per-vnet - srfd-reserved-vcs
```

One retained cache block occupies one data VC. Incomplete retained packets
count toward the cap, so interleaved packet headers cannot exceed it.

For the current six-VC configuration:

| Flag | Hard retained-block cap |
|---|---:|
| `--srfd-reserved-vcs=0` | 6; previous behavior |
| `--srfd-reserved-vcs=1` | 5 |
| `--srfd-reserved-vcs=2` | 4; current headroom experiments |
| `--srfd-reserved-vcs=6` | 0; no retention |

Each retained 64-byte block occupies one data VC (five 128-bit flits). The
4x4 experiment has 16 participating L2-facing local inputs, one per router.
The old six-block cap therefore permits at most 16 x 6 = **96 retained
blocks** across the NoC. Reserving two VCs permits at most 16 x 4 = **64
retained blocks**. Other local controller links do not add SRFD capacity
because they do not inject messages marked for SRFD storage.

Values below zero or above `--vcs-per-vnet` are rejected. The previous roughly
five-block figure was average occupancy, not a five-block hard limit.

This reserves capacity **against persistent SRFD retention**. Ordinary
in-flight packets can occupy that capacity; it does not guarantee that
particular VC IDs remain idle. Control vnets are not reduced.

At the cap:

- Dirty candidates continue along their ordinary memory writeback route.
- Clean candidates are assembled and discarded when the tail arrives, with
  credits returned and pending-store notifications resolved. They are not
  forwarded as unexpected clean writebacks to memory.
- `dirty_bypassed` and `clean_bypassed` count these admission decisions.
  They are separate from releases of blocks that were already retained.

Reservation applies in both aggressive and defensive modes. The zero default
matched the preserved binary's randomized simulated ticks and reply counts.

## Network configuration

| Direct gem5 flag | Parser default | Current 4x4 experiment value |
|---|---:|---|
| `--network` | `simple` | `garnet` |
| `--topology` | `Crossbar` | `MeshDirCorners_XY` |
| `--mesh-rows` | 0 | 4 |
| `--vcs-per-vnet` | 4 | 6 |
| `--buffers-per-data-vc` | 4 | 5 |
| `--buffers-per-ctrl-vc` | 1 | 1 |
| `--link-width-bits` | 128 | 128 |
| `--router-latency` | 1 | 2 |
| `--link-latency` | 1 | 1 |
| `--routing-algorithm` | 0, table routing | 1, XY routing |

VC count and flit-buffer depth are different: six VCs per vnet means six
packet channels; five data buffers means five flits can fit in each data VC.
With three vnets, there are 18 VCs per input in total. For 64-byte blocks and
128-bit links, SRFD data packets occupy five flits; explicitly use five data
buffers. A packet that cannot fit in one data VC is rejected.

The 4x4 setup uses `--num-cpus=16`, `--num-l2caches=16` and `--num-dirs=4`.
Directory routers are 0, 3, 12 and 15. CPU, system and Ruby clocks are 2GHz;
private split L1s are 16KB and each shared LLC bank is 128KB.

## Small data-checking example

Run from the repository through the existing local container. Use a fresh
output directory; this is a protocol smoke, not a SPEC performance result.

```bash
docker exec -w /docker_mounted_gem5 gem5_fs_dev \
  build/X86_MOESI_CMP_directory/gem5.opt \
  -d PAPER_TESTS/example_cbdb_reserved2 \
  configs/example/ruby_random_test.py \
  --ruby --num-cpus=4 --num-l2caches=4 --num-dirs=4 \
  --network=garnet --topology=MeshDirCorners_XY --mesh-rows=2 \
  --vcs-per-vnet=6 --buffers-per-data-vc=5 --link-width-bits=128 \
  --router-latency=2 --routing-algorithm=1 \
  --srfd-mode=cbdb-aggressive --srfd-reserved-vcs=2 --maxloads=20000
```

For `srfd_eval.py`, use `--profile=corners-4x4-6vc`,
`--srfd-modes=cbdb-aggressive,cbdb-defensive` and `--srfd-reserved-vcs=2`.
That driver is the SE workflow; an instruction fast-forward alone does not
identify a computation-only application ROI.
