# TASK1
#### 1.  
    In the previous week we already added support for printing packet route so only need to send ack in this task.
    we send ack in network interface when we receive a packet whose destination is that router we generate and ack
    packet with id negative of that packets id so that we can see it easily in the output file.
    functionality taken from flitisize message and intercepted earlier in wakeup.
### 2. Router Packet Latency

* Time a packet/flit spends being processed inside a router.
* Includes routing, VC allocation, switch allocation, and traversal delays.
* Mainly controlled by Garnet's router pipeline/timing.
* Increasing it → higher packet/network latency and earlier network saturation.

### 3. Network Latency & Queueing Latency

* **Network latency:** Time from network injection at source NI to ejection at destination NI.
* **Queueing latency:** Time a flit spends waiting in router buffers for a VC/output/switch.
* Higher injection rate → more congestion → higher queueing latency → higher network latency.
* Stats: `average_packet_network_latency`, `average_flit_network_latency`, `average_flit_queueing_latency`.

### 4. Cache Coherency Protocols in gem5

* Maintain consistency when multiple CPU caches hold the same memory data.
* Common Ruby protocols: **MESI, MOESI, MI_example, CHI**.
* **MESI:** standard/simple; **MOESI:** adds Owned state; **CHI:** Arm coherent systems; **MI_example:** learning/custom protocols.
* **Garnet standalone** is used when studying the NoC itself, without a real cache-coherence workload.
