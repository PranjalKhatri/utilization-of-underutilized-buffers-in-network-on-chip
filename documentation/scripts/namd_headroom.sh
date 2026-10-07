#!/bin/sh
set -eu

reserved_vcs=${1:-2}
status=PAPER_TESTS/srfd_headroom_20261006/workflow_status.json

if [ -f "$status" ]; then
    echo "Existing workflow state:"
    sed -n '1,80p' "$status"
    echo "The preserved workflow directory is single-use; use namd_checkpoint.sh with fresh output paths for a new run." >&2
    exit 1
fi

exec docker exec -w /docker_mounted_gem5 gem5_fs_dev \
    python3 PAPER_TESTS/srfd_headroom_20261006/run_experiments.py \
    --reserved-vcs="$reserved_vcs"
