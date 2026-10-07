#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: $0 OUTPUT MODE RESERVED_VCS" >&2
    exit 2
fi

output=$1
mode=$2
reserved_vcs=$3

exec docker exec -w /docker_mounted_gem5 gem5_fs_dev \
    build/X86_MOESI_CMP_directory/gem5.opt -d "$output" \
    configs/example/ruby_random_test.py \
    --ruby --num-cpus=4 --num-l2caches=4 --num-dirs=4 \
    --network=garnet --topology=MeshDirCorners_XY --mesh-rows=2 \
    --vcs-per-vnet=6 --buffers-per-data-vc=5 --link-width-bits=128 \
    --router-latency=2 --routing-algorithm=1 --maxloads=20000 \
    --srfd-mode="$mode" --srfd-reserved-vcs="$reserved_vcs"
