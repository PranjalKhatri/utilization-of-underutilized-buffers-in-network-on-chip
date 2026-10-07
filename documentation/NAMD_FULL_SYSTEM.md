# NAMD full-system 4x4 workflow

This is the reproducible workflow used for the computation-only NAMD results.
Commands are run from the repository root. The Docker container mounts it as
`/docker_mounted_gem5`; gem5 must run with the container Python runtime.

## Configuration used

| Item | Value |
|---|---|
| ISA and protocol | x86, `MOESI_CMP_directory` |
| CPUs | 16 `X86O3CPU` during warmup and measurement |
| Topology | 4x4 `MeshDirCorners_XY` |
| L2/LLC banks | 16, one per mesh router |
| Directories | 4, routers 0, 3, 12 and 15 |
| Network | Garnet, six VCs/vnet, five data buffers/VC |
| Link/router | 128-bit links, one-cycle links, two-cycle routers, XY routing |
| Memory and clocks | 3GB; CPU, Ruby and system at 2GHz |
| Measurement | 100k minimum warmup + 20M minimum ROI instructions per core |
| Disk I/O | PIO; root and payload images are copy-on-write/read-only |

The checkpoint geometry is part of the checkpoint. A 2x2 checkpoint cannot be
restored as 4x4. Create the 4x4 checkpoint once, then restore the same checkpoint
for every mode being compared.

## Required files

- `build/X86_MOESI_CMP_directory/gem5.opt`
- `/root/.cache/gem5/x86-linux-kernel-4.19.83-1.0.0` in the container
- `/root/.cache/gem5/x86-parsec-1.0.0` as the bootable Ubuntu image
- `cpu2017/cpu2017/binaries/namd`
- `cpu2017/cpu2017/data/namd/all/input/namd.input`
- `util/m5/build/x86/out/m5`
- the computation hook and payload under
  `PAPER_TESTS/namd_compute_roi_20261006/`

The PARSEC-labelled image supplies only the guest Linux installation. The
measured program is the separately mounted SPEC NAMD binary and input.

## How the computation ROI was found

An instruction count alone does not identify a useful phase. The selected
boundary was established in four steps:

1. Run NAMD natively and inspect symbols/disassembly around
   `ComputeList::runComputes(PatchList*)`.
2. Interpose that function with `compute_gate.so`, log every entry and return
   address, and verify that each NAMD invocation has the same call sequence.
3. Profile the selected call with native `perf`. The samples must resolve to
   `ComputeNonbondedUtil::calc_pair_energy` and `calc_self_energy`, confirming
   that the region is force computation rather than input or initialization.
4. Run unmodified and hooked NAMD instances and byte-compare `result.output`.

The selected marker is call 7 at function offset `0x3830`, returning to main
offset `0x1625`. Calls 1--6 execute the six force modes of iteration 0. Call 7
is the first force mode of iteration 1. The hook places every worker at a common
barrier, emits `workbegin` when all workers arrive, and emits a per-worker
`workend` when that selected call returns.

These addresses and the expected 14-byte function prologue are specific to the
current NAMD binary. The hook fails closed if the prologue or call site changes.
Repeat symbol inspection, profiling and output validation for another binary.

## Payload and hook preparation

The preserved workflow sources are in
`PAPER_TESTS/namd_compute_roi_20261006/`. Build the hook using the same guest
compatible ABI, then build the read-only payload image:

```bash
gcc -shared -fPIC -O2 \
  -o PAPER_TESTS/namd_compute_roi_20261006/compute_gate.so \
  PAPER_TESTS/namd_compute_roi_20261006/compute_gate.c -ldl

python3 PAPER_TESTS/namd_compute_roi_20261006/native_validate.py
python3 PAPER_TESTS/namd_compute_roi_20261006/build_payload.py
```

`build_payload.py` creates a 128MB ext2 image containing NAMD, its data, the
hook and the `m5` utility. It also records SHA-256 hashes. It deliberately
refuses to overwrite its staging directory or image.

## Validate with 2x2 before 4x4

Run the four-core validation before spending time on a 16-core simulation:

```bash
docker exec -w /docker_mounted_gem5 gem5_fs_dev \
  python3 PAPER_TESTS/namd_compute_roi_20261006/run_validation.py
```

This creates a baseline cold checkpoint, restores it with KVM through complete
program output, compares all four outputs with the native gold output, and runs
short O3 baseline and SRFD measurements. Every row in `validation_results.json`
must pass.

## Create the 4x4 computation checkpoint

Use the documented wrapper with two new paths under `PAPER_TESTS`:

```bash
bash documentation/scripts/namd_checkpoint.sh create \
  PAPER_TESTS/my_namd_run/cpt_4x4_compute \
  PAPER_TESTS/my_namd_run/create_4x4
```

The guest boots on KVM, starts 16 pinned NAMD copies, skips input and the first
six computation calls, and stops on the common call-7 `workbegin`. Only baseline
may create a checkpoint. Ruby caches are cold in the saved state; active SRFD
checkpoint creation is intentionally rejected.

Creation is successful only when `fs_roi_status.json` says
`checkpoint_complete`, `post_input_metadata.json` records call 7 and
`creation_manifest.json` records matching binary/payload hashes.

## Restore and measure with O3

Restore into a fresh output directory for each mode. Example cap-four runs:

```bash
bash documentation/scripts/namd_checkpoint.sh restore \
  PAPER_TESTS/my_namd_run/cpt_4x4_compute \
  PAPER_TESTS/my_namd_run/roi_cbdb_aggressive \
  cbdb-aggressive 2 100000 20000000

bash documentation/scripts/namd_checkpoint.sh restore \
  PAPER_TESTS/my_namd_run/cpt_4x4_compute \
  PAPER_TESTS/my_namd_run/roi_cbdb_defensive \
  cbdb-defensive 2 100000 20000000
```

The restore initializes gem5, performs `simulate(0)`, switches all CPUs from
KVM to O3, warms each CPU for at least 100k instructions, resets statistics,
then measures until every CPU retires at least 20M instructions. Faster CPUs
remain active, so aggregate instruction totals differ between runs. Compare
aggregate IPC and also report the actual per-core counts and completion ticks.

Every CPU has an end marker. If any worker exits the selected call before all
instruction targets are reached, the run fails instead of including a later
phase. `--roi-seconds` is a simulated-time safety bound; `--timeout` is host
wall time.

For the already validated headroom workflow, the exact command used was:

```bash
docker exec -w /docker_mounted_gem5 gem5_fs_dev \
  python3 PAPER_TESTS/srfd_headroom_20261006/run_experiments.py \
  --reserved-vcs=2
```

That orchestrator checks reservation regressions, validates the hash-pinned
cold checkpoint with a complete KVM run, performs 2x2 O3 smokes, then runs the
4x4 aggressive and defensive cases serially. Its directory is single-use; do
not rerun it over completed outputs.

## Watch, validate and analyze

```bash
python3 documentation/scripts/namd_status.py PAPER_TESTS/my_namd_run/roi_cbdb_aggressive
python3 documentation/scripts/namd_summary.py \
  PAPER_TESTS/srfd_headroom_20261006/results.json
```

Required evidence in each output directory:

- `verification.json`: process and phase verdict.
- `fs_roi_status.json`: live phase, per-core counts and marker events.
- `roi_stats.txt`: stats reset at ROI start and dumped at ROI end.
- `manifest.json`, `command.json`, `config.json`, `source_snapshot/`: provenance.
- `analysis.json`: derived IPC, LLC penalty and checked SRFD accounting.

Reject a comparison if the run reports an end-marker event, any core misses its
budget, `simTicks`/`simInsts` disagree with the phase record, geometry differs,
the storage cap is exceeded, or lifecycle accounting fails.

## Checkpoint compatibility rules

gem5 checkpoints are normally tied to the creator binary. The headroom run used
a narrow compatibility exception only for the existing hash-pinned cold
baseline call-7 checkpoint: unchanged payload, unchanged geometry, no Ruby
cache trace, and a successful complete KVM output comparison were mandatory.
Do not use that path as a general binary-mismatch bypass.

The implementation rejects coherent DMA and active-SRFD checkpointing. PIO is
therefore part of this validated configuration.
