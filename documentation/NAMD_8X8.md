# 8x8 NAMD computation-only comparison

The 64-core workflow uses O3 CPUs, MeshDirCorners_XY, four corner directories,
six VCs/vnet, five flits/data VC, 128-bit links and 2GHz clocks. It creates a
fresh baseline checkpoint at computation call 7 for the 8x8 geometry, excludes
input preparation, warms each core for at least 100k instructions and measures
at least 20M ROI instructions/core. All cores stay active until the slowest
reaches target; actual instruction totals are recorded.

## Memory configuration

A native two-iteration NAMD process peaked at 160,564 KiB RSS. Sixty-four
copies could therefore require roughly 10 GiB before guest-kernel overhead.
Use a **16 GiB guest**, rather than the earlier 3 GiB configuration.

The legacy Ruby `--access-backing-store` shadow covers only the first RAM
range. x86 splits RAM above 3 GiB around its device-address hole. This workflow
uses `--no-access-backing-store`, allowing KVM to map the actual DRAM backing
stores, whose interleaved directory ranges are merged by PhysicalMemory.
O3 then reads/writes those same memories through Ruby rather than overwriting
responses with the lower-range-only shadow. The old 3 GiB workflow defaults
remain unchanged.

Memory size and backing mode are recorded in checkpoint metadata and manifests;
the launcher rejects restoring a checkpoint with a different configuration.

## Validation and queued runs

Before long measurements, the script creates a 2x2 checkpoint with the new
memory configuration, verifies complete KVM outputs against native NAMD, and
runs a 1M-instruction/core directional O3 smoke. It then creates and validates
the 64-core checkpoint and performs short 8x8 O3 smokes for each configuration.
Any failure stops the workflow and preserves diagnostic logs.

| Case | Directional storage | Retention cap per eligible input |
|---|---|---:|
| Local baseline | Off | No retention |
| Local CB+DB aggressive | Off | 6 |
| Local CB+DB aggressive | Off | 4 |
| Escape-reserved baseline | On | No retention |
| Directional CB+DB aggressive | On | 4 |
| Directional CB+DB aggressive | On | 5 |

Directional cap 6 is unsupported with six physical VCs: one VC remains the
unborrowable escape path. Cap 5 is the maximum valid counterpart. Compare
Local cases against the Local baseline and directional cases against the
escape-reserved baseline.

```sh
docker exec -d -w /docker_mounted_gem5 gem5_fs_dev sh -c \
  'PYTHONDONTWRITEBYTECODE=1 python3 documentation/scripts/namd_8x8_sweep.py \
  --output=PAPER_TESTS/namd_8x8_20261008 \
  > PAPER_TESTS/namd_8x8_20261008/workflow.log 2>&1'
```

Create the output parent before shell redirection when using a fresh directory.
`--roi-insts` changes the per-core measurement target; default is 20M.
`--no-directional-cap5` omits the optional maximum-cap directional case.
Jobs run serially, wait for at least 20 GiB host MemAvailable, and sleep while
waiting. Each child has a 48-hour wall-time limit.

`workflow_status.json` identifies the active case. Each run records live
`fs_roi_status.json`, commands, source provenance, binary/payload hashes,
verification, ROI statistics and analysis. `results.json` accumulates completed
measurements and their IPC/LLC ratios against the correct baseline.
