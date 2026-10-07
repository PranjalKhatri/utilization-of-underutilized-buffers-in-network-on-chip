# Build and validation

## Directional storage validation

The implementation audit is in `PAPER_TESTS/srfd_directional_20261007/`.
`run_random.py` runs 13 seeded comparisons/cases, including preserved-binary
Local-only comparisons, 2x2/4x4 meshes, caps 4 and 5, DB/CB+DB policies,
zero-capacity bypass and mid-run statistics resets with longer link latency.
`run_negative.py` checks invalid configurations and the explicit disable flag.

All 13 cases passed with 22,936 directional hits and 23,310 neighbour-triggered
releases across the measured test windows. The disabled baseline and CB+DB
cases matched preserved simulation ticks and principal SRFD counters exactly.
Complete baseline KVM restores matched native NAMD outputs for both 2x2 and
4x4 checkpoints. An additional 2x2 O3 computation-only NAMD smoke measured
at least 1M instructions/core and exercised 937 leases, 875 directional
pressure releases and 50 directional hits with balanced lifecycle counters.
The experiment directory
`PAPER_TESTS/namd_directional_20261007/` holds the O3 smokes and serial long-run
workflow. See [DIRECTIONAL_SRFD.md](DIRECTIONAL_SRFD.md) for run commands and
modeled hardware assumptions.

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
