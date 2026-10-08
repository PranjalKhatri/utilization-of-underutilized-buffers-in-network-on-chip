# SRFD implementation and experiment documentation

- [Directional SRFD storage](DIRECTIONAL_SRFD.md): dynamic neighbour leases,
  escape routing, pressure recovery, toggles and the NAMD comparison workflow.
- [Escape VC examples](ESCAPE_VC_EXPLAINED.md): circular waits, reservation,
  and how an East-stored packet leaves through North or a Local output.
- [8x8 NAMD workflow](NAMD_8X8.md): 64-core checkpoints, large-memory validation
  and matched Local/directional cap comparisons.

This folder documents this repository's router-buffer implementation and the
SPEC experiment workflows. gem5's upstream documentation remains in `docs/`.

- [SRFD and network flags](SRFD_FLAGS.md): operating modes, reserved capacity,
  network settings, defaults and examples.
- [Computation-only experiments](EXPERIMENTS.md): checkpoints, warmup/ROI
  budgets, launch commands, status files and supported workloads.
- [NAMD full-system workflow](NAMD_FULL_SYSTEM.md): finding the computation
  ROI, validating the hook, building the payload, creating/restoring the
  checkpoint, running the 4x4 O3 comparison and diagnosing failures.
- [Testing](TESTING.md): build, evaluator, randomized protocol, checkpoint and
  full-system validation gates.
- [Statistics and comparisons](METRICS.md): IPC, LLC latency, clean/dirty hits,
  pressure releases, bypasses, occupancy and host throughput.
- [Reusable scripts](scripts/README.md): wrappers for checkpoint creation,
  restoration, the headroom workflow, status reporting and regression tests.

All experiment outputs, audits, smoke tests and diagnostic scripts belong in
`PAPER_TESTS/`, which is ignored by git. The reusable documentation lives here.

The headroom change and its verification are documented in
`PAPER_TESTS/srfd_headroom_20261006/IMPLEMENTATION_AND_LAUNCH.md`; the exact change
against preserved pre-edit sources is `implementation.patch` in that folder.
