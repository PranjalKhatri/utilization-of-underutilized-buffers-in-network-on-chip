in RoutingUnit.cc add the algorithm
also added it as param in config/network.py and in enum in common types
./build/Garnet_standalone/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet \
    --num-cpus=16 \
    --num-dirs=16 \
    --topology=Mesh_XY \
    --mesh-rows=4 \
    --routing-algorithm=3 \
    --synthetic=uniform_random \
    --injectionrate=0.05 \
    --sim-cycles=10000