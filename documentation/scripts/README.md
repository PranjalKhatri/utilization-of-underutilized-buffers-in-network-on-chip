# Experiment helper scripts

Run these from the repository root. They keep all generated output in the
ignored `PAPER_TESTS/` tree.

| Script | Purpose |
|---|---|
| `namd_checkpoint.sh` | Create a 4x4 call-7 checkpoint or restore it for an O3 ROI |
| `namd_headroom.sh` | Invoke the validated aggressive/defensive headroom workflow |
| `namd_status.py` | Show phase, per-core progress and completion state |
| `namd_summary.py` | Print the principal IPC, LLC and SRFD fields from results JSON |
| `srfd_random_smoke.sh` | Run a fresh 2x2 RubyRandomTester data-checking smoke |
| `srfd_regressions.sh` | Run evaluator tests and the historical reservation matrix |

The wrappers intentionally call the preserved, audited drivers under
`PAPER_TESTS/namd_compute_roi_20261006/` and
`PAPER_TESTS/srfd_headroom_20261006/`. Those directories contain the exact
guest scripts, checkpoint driver, hook source, source snapshots and validation
records used for the reported experiments. See `NAMD_FULL_SYSTEM.md` before
creating a new checkpoint.

The `reference/` subdirectory contains tracked, byte-for-byte source copies of
the principal scripts used for the completed run. They are provenance copies:
some preserve relative paths to their original `PAPER_TESTS` working directory
and should not be run in place. The top-level wrappers above are the supported
entry points.
