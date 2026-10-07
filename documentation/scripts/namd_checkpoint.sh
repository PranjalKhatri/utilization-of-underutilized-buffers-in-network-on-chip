#!/bin/sh
set -eu

usage() {
    echo "usage:" >&2
    echo "  $0 create CHECKPOINT OUTPUT" >&2
    echo "  $0 restore CHECKPOINT OUTPUT MODE RESERVED_VCS WARMUP_INSTS ROI_INSTS" >&2
    exit 2
}

[ "$#" -ge 1 ] || usage
action=$1
shift

case "$action" in
create)
    [ "$#" -eq 2 ] || usage
    checkpoint=$1
    output=$2
    exec docker exec -w /docker_mounted_gem5 gem5_fs_dev \
        python3 PAPER_TESTS/srfd_headroom_20261006/run_checkpoint.py \
        --action=create --mesh-rows=4 --mode=baseline \
        --checkpoint="$checkpoint" --output="$output" \
        --timeout=86400 --roi-seconds=120
    ;;
restore)
    [ "$#" -eq 6 ] || usage
    checkpoint=$1
    output=$2
    mode=$3
    reserved_vcs=$4
    warmup_insts=$5
    roi_insts=$6
    exec docker exec -w /docker_mounted_gem5 gem5_fs_dev \
        python3 PAPER_TESTS/srfd_headroom_20261006/run_checkpoint.py \
        --action=restore --mesh-rows=4 --mode="$mode" \
        --srfd-reserved-vcs="$reserved_vcs" \
        --checkpoint="$checkpoint" --output="$output" \
        --warmup-insts="$warmup_insts" --roi-insts="$roi_insts" \
        --roi-cpu=o3 --timeout=86400 --roi-seconds=120
    ;;
*) usage ;;
esac
