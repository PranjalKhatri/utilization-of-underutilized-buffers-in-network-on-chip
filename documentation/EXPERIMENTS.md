# Computation-only experiments

## Workload boundaries

| Workload | Saved computation boundary | Measured minimum/core | Output directory |
|---|---|---:|---|
| NAMD, original computation comparison | `ComputeList::runComputes` call 7, after all six modes of iteration 0 | 20M | `PAPER_TESTS/namd_compute_roi_20261006/` |
| NAMD, reserved-capacity comparison | Same checkpoint and boundary | 20M | `PAPER_TESTS/srfd_headroom_20261006/` |
| Cactus | First `ML_BSSN_RHS_Body` call in timestep 2, after one complete RK3 timestep | 5M | `PAPER_TESTS/cactus_compute_roi_20261006/` |

The long runs use 16 O3 cores, 4x4 `MeshDirCorners_XY`, six VCs/vnet and
100k minimum timing warmup instructions per core. Cactus uses the explicitly
selected supplied test input, a 42-cubed grid, with one thread per copy.
NAMD uses the original binary with a runtime computation-entry hook.

The binary files and mathematical kernel bodies are unchanged. Runtime entry
trampolines add a common start barrier and a per-core end marker. If any core
leaves the selected computation call before the required window finishes,
the measurement fails; later output or computation is not silently included.
Kernel interruptions inside a full-system computation window remain counted.
Native profiling and complete KVM output comparisons validate the boundaries.

All cores remain active until every core reaches its target, so faster cores
retire extra instructions. Record the actual per-core counts. This differs
from the older SE workflow that paused individual cores at their budgets.
KVM checkpoints have cold Ruby caches; 100k warmup does not establish that an
instruction window reproduces the paper's representative-window policy.

## Headroom experiment launcher

The existing launch is controlled by:

```text
PAPER_TESTS/srfd_headroom_20261006/run_experiments.py --reserved-vcs=2
```

This script requires successful reservation regressions, validates restoration
from the existing cold checkpoint, and runs O3 smokes. It then runs CB+DB
aggressive followed by CB+DB defensive at a four-block cap, waiting for memory
availability before each large process. It reads the completed baseline
result; it does not launch a baseline timing run.

The recorded workflow completed successfully for both modes. Do not start a
duplicate in the same directory. For a new experiment, create a fresh output
layout and preserve old results. The launcher creates output directories with
`exist_ok=False`.

## Single restore flags

`PAPER_TESTS/srfd_headroom_20261006/run_checkpoint.py` supports:

| Flag | Meaning |
|---|---|
| `--action=restore` | Restore the selected checkpoint |
| `--checkpoint=PATH` | Saved cold baseline computation checkpoint |
| `--output=PATH` | New output directory under `PAPER_TESTS` |
| `--mesh-rows=4` | 16 cores in the square mesh; must match saved geometry |
| `--mode=cbdb-aggressive` or `cbdb-defensive` | Operating mode |
| `--srfd-reserved-vcs=2` | Four-block retained-storage cap with six VCs |
| `--warmup-insts=100000` | Minimum timing warmup per core |
| `--roi-insts=20000000` | Minimum measured instructions per core |
| `--roi-cpu=o3` | Measured CPU; `kvm` is used for full-output validation |
| `--roi-seconds=120` | Simulated-time bound for each timing phase, not host seconds |
| `--timeout=86400` | Host wall-clock timeout in seconds |
| `--trace-roi` | Enable Exec tracing during measurement; output can be large |

The launcher defaults for instruction budgets are not the requested experiment
budgets: always pass warmup and ROI explicitly. The original NAMD launcher has
no reservation argument; use the headroom launcher for that feature.

The Docker working directory is `/docker_mounted_gem5`, corresponding to the
host repository. The existing binary requires the container's Python runtime.

## Checkpoint and disk support

These FS workflows use the existing Ubuntu disk as a guest OS, not PARSEC
benchmarks. SPEC payloads are separate read-only images; root disks use COW.
PIO is enforced because coherent DMA with active SRFD is unsupported and
rejected. Active SRFD checkpoint creation/writeback also remains unsupported.
The saved checkpoints were made under baseline KVM before SRFD timing starts.

The reservation build has a different binary hash. Its isolated compatibility
path allows only the hash-pinned, cold baseline computation checkpoints with
unchanged payload and geometry. A complete four-copy KVM restore/output
comparison must pass before timing runs are allowed. This is recorded in
`checkpoint_compatibility.json`; it is not a general checkpoint-compatibility
option and must not be used to bypass an unrelated binary change.

The supplied MCF binaries use AVX instructions unsupported by the configured
guest. Its prepared workflow is in `PAPER_TESTS/mcf_compute_roi_20261006/`,
but no valid FS MCF comparison was launched. A guest-compatible build/source
is needed first.

## Live status and results

- `workflow_status.json`: current headroom case, storage cap and memory waits.
- `roi_4x4_MODE/fs_roi_status.json`: phase and live per-core instruction counts.
- `verification.json`: completion verdict and recorded phase counts.
- `command.json`, `manifest.json`, `source_snapshot/`, `config.json`: provenance.
- `roi_stats.txt`: statistics dumped after the measured ROI.
- `analysis.json`: derived IPC, latency, storage, pressure and accounting checks.
- `results.json` / `RESULTS.md`: headroom comparison as each mode finishes.
- `RUN_FAILED.json` and `run.log`: failure details; no valid speedup is implied.

The original NAMD workflow uses `results_4x4.json` and `comparison_4x4.json`.
Its DB-only extension writes `comparison_db_aggressive.json` and `DB_RESULTS.md`.
Historical post-input and SE results remain preserved in separate folders.
