./build/X86/gem5.opt configs/deprecated/example/se.py -c tests/test-progs/hello/bin/x86/linux/hello
scons build/X86/gem5.opt -j 14
add actions in src/mem/ruby/protocol/mesi_two_level_l1_cache.sm
define scalar variable in statistics
python3 -m pip install --break-system-packages matplotlib
apt install -y python3-pip
export PYTHONPATH=/docker_mounted_gem5/configs:$PYTHONPATH
docker exec -it gem5_dev bash
tmux
Ctrl-B, then D
and next time
docker exec -it gem5_dev bash
docker exec -it gem5_dev tmux attach -t gem5

docker run -it -v /home/pranjal/gem5:/docker_mounted_gem5 --name gem5_dev gem5 bin/bash
docker start -ai gem5_dev
run without ruby and for week2 q2 min size is 16
./build/X86/gem5.opt configs/deprecated/example/se.py --sys-clock=2GHz --mem-size=8GB --caches --l2cache -I 20000 --bench=namd --ruby

for adding methods in slic files add first to RubySliccc_Types.sm file and then make them public in your hh file.

week4:
2>
a> src/mem/ruby/network/garnet/     NetworkInterface.cc
GARNET STANDALONE BUIKD
# 1. Build the standalone Garnet binary
scons build/NULL/gem5.opt PROTOCOL=Garnet_standalone -j$(nproc)
scons build/Garnet_standalone/gem5.opt  PROTOCOL=Garnet_standalone -j$(nproc)
# 2. Run the synthetic simulation
./build/NULL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet \
    --num-cpus=16 \
    --num-dirs=16 \
    --topology=Mesh_XY \
    --mesh-rows=4 \
    --synthetic=uniform_random \
    --injectionrate=0.02 \
    --vcs-per-vnet=4 \
    --sim-cycles=20000


week6 for fs emulation created new container
docker run -d \
  --name gem5_fs_dev \
  --device=/dev/kvm \
  -v /home/pranjal/gem5:/docker_mounted_gem5 \
  gem5 \
  sleep infinity

  docker exec -it gem5_fs_dev bash

docker stop gem5_fs_dev 2>/dev/null
docker rm gem5_fs_dev 2>/dev/null

docker run -d \
  --name gem5_fs_dev \
  --device=/dev/kvm \
  --cap-add=PERFMON \
  -v /home/pranjal/gem5:/docker_mounted_gem5 \
  gem5 \
  sleep infinity

docker exec -it gem5_fs_dev bash