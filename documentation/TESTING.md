# Build and validation

Run generated artifacts under `PAPER_TESTS/`; keep repository sources and
documentation outside it.

## Build

```bash
scons build/X86_MOESI_CMP_directory/gem5.opt \
  PROTOCOL=MOESI_CMP_directory -j4 --linker=gold --limit-ld-memory-usage
```

The gold linker avoids the high peak memory seen with the default BFD link.

## Evaluator unit tests

```bash
docker exec -w /docker_mounted_gem5 gem5_fs_dev \
  python3 -m unittest \
  PAPER_TESTS/corrections_20261005/test_evaluator.py \
  PAPER_TESTS/corrections_20261005/test_roi_polling.py
```

These cover lifecycle accounting, lost notification/reply rejection, ROI
budget validation and VC-availability aggregation.

## Randomized Ruby/Garnet smoke

```bash
bash documentation/scripts/srfd_random_smoke.sh \
  PAPER_TESTS/manual_random_cbdb cbdb-aggressive 2
```

This runs four RubyRandomTester CPUs on a 2x2 mesh, checks memory data, and
exercises the six-VC cap-four configuration. Use a fresh output directory.

## Reservation regression matrix

```bash
bash documentation/scripts/srfd_regressions.sh
```

The historical matrix checks the preserved binary against the new default,
cap four, cap one, cap zero, aggressive/defensive behavior, overflow bypass,
negative/excessive flag rejection and lifecycle accounting. It needs the
preserved `gem5_before.opt` and is single-use because its output directories
are created with `exist_ok=False`.

## Full-system validation order

1. Native hooked/unhooked output comparison.
2. 2x2 baseline checkpoint creation.
3. Complete 2x2 KVM restore and output comparison.
4. Short 2x2 O3 baseline and SRFD measurements.
5. 4x4 baseline checkpoint creation.
6. 4x4 O3 measured modes, one at a time.
7. Verify marker guards, instruction budgets, configuration and accounting.

Do not infer a valid speedup from a process exit code alone. Use
`verification.json`, phase counts and `roi_stats.txt`.
