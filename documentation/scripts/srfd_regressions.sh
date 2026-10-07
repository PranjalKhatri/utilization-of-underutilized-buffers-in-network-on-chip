#!/bin/sh
set -eu

docker exec -w /docker_mounted_gem5 gem5_fs_dev \
    python3 -m unittest \
    PAPER_TESTS/corrections_20261005/test_evaluator.py \
    PAPER_TESTS/corrections_20261005/test_roi_polling.py

exec docker exec -w /docker_mounted_gem5 gem5_fs_dev \
    python3 PAPER_TESTS/srfd_headroom_20261006/run_reservation_tests.py
