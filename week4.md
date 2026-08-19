In **GEM5**, Network-on-Chip (NoC) simulations are typically handled by the Ruby memory system, which provides two primary network models: the detailed **Garnet** model and the **Simple Network** model.

Here are the key files related to packet transmission for both models.

NOC is made up of both interconnect model and topology.

### Garnet Network Model (Detailed NoC)

Garnet models a detailed microarchitectural NoC where packets are broken down into flits (flow control units).

* **`src/mem/ruby/network/garnet/NetworkInterface.cc`**: This is the bridge between the memory controllers and the NoC. It dequeues messages from the memory system, breaks them into packets/flits, and injects them into the network.
* **`src/mem/ruby/network/garnet/flit.cc`**: Defines the flit data structure. Since packets are transmitted flit-by-flit in a realistic NoC, this file contains the properties of the transmission unit (e.g., flit type, VC allocation, timestamp).
* **`src/mem/ruby/network/garnet/NetworkLink.cc`**: Models the physical wires. It handles the actual transmission delay and bandwidth constraints as flits travel from one router to another.
* **`src/mem/ruby/network/garnet/Router.cc`**: The main router class. It orchestrates the internal pipeline (routing, switch allocation, VC allocation) required to transmit a packet to its next hop.
* **`src/mem/ruby/network/garnet/OutputUnit.cc`**: Manages the router's output ports. It wakes up the connected `NetworkLink` to physically transmit the flit to the next node.

### Simple Network Model

The Simple Network is an abstract model that transmits whole messages rather than breaking them into flits, focusing on latency and bandwidth without detailed router microarchitecture.

* **`src/mem/ruby/network/simple/PerfectSwitch.cc`**: Acts as a crossbar that routes and transmits entire messages from input ports to output ports based on routing tables.
* **`src/mem/ruby/network/simple/Throttle.cc`**: Controls the flow of messages. It enforces link bandwidth and models the link transmission latency for the packets passing through the simple network.

### General Ruby Network Interfaces

* **`src/mem/ruby/network/MessageBuffer.cc`**: The queues that act as the interface between cache/directory controllers and the NoC. Packets are buffered here before the `NetworkInterface` picks them up for transmission.

---


This header file (`NetworkInterface.hh`) defines the **Garnet Network Interface (NI)** in gem5. It serves as the bridge between Ruby's cache coherence protocol controllers (SLICC) and the detailed Garnet Network-on-Chip (NoC).

---

### Key Structures & Helper Classes

* **`NetworkInterface` (Class):**
* **What it does:** Inherits from `ClockedObject` (cycle-driven) and `Consumer` (responds to queue wakeups). It receives coherence messages from protocol controllers, chops them into flits (flow control units), injects them into the network, and reassembles incoming flits back into messages for the coherence protocol.


* **Why:** Protocols operate on coarse messages (requests/responses), while Garnet operates on cycle-by-cycle flits. The NI converts between these two domains and handles flow control.




* **`OutputPort` (Nested Class):**
* **What it does:** Encapsulates an outbound path into the network. Holds pointers to the outgoing data link (`_outNetLink`), the incoming credit link (`_inCreditLink`), a flit buffer queue (`_outFlitQueue`), connected router ID, bit-width, and supported Virtual Networks (Vnets).
* **Why:** Allows an NI to connect to multiple physical router links while managing flit buffering, serialization width, and round-robin VC scheduling independently per port.


* **`InputPort` (Nested Class):**
* **What it does:** Encapsulates an inbound path from the network. Manages the incoming data link (`_inNetLink`), outbound credit link (`_outCreditLink`), a credit queue (`_outCreditQueue`), and a stall queue (`m_stall_queue`).
* **Why:** Buffers incoming flits, handles backpressure/stalls when destination message buffers are full, and returns flow-control credits upstream to the sender router.



---

### Member Functions

#### Lifecycle & Port Setup

* **`NetworkInterface(const Params &p)` / `~NetworkInterface()`:** Constructor/destructor for initialization.
* **`addInPort(NetworkLink *in_link, CreditLink *credit_link)`:** Binds an incoming physical data link and its corresponding reverse credit link.
* **`addOutPort(NetworkLink *out_link, CreditLink *credit_link, SwitchID router_id, uint32_t consumerVcs)`:** Binds an outgoing physical data link, reverse credit link, destination router ID, and allocates downstream consumer Virtual Channels (VCs).
* **`addNode(std::vector<MessageBuffer *> &inNode, std::vector<MessageBuffer *> &outNode)`:** Connects the NI to the SLICC cache controller message queues. `inNode` takes messages from SLICC to inject into NoC; `outNode` delivers arriving messages back to SLICC.


* **`init_net_ptr(GarnetNetwork *net_ptr)`:** Sets the pointer to the overarching Garnet network object.

#### Protocol & Simulation Engine Hooks

* **`wakeup()`:** The main cycle event handler. Processes incoming flits from network links, consumes protocol messages from `inNode`, and drives arbitration.
* **`dequeueCallback()`:** Called when a message buffer slot opens up, waking up stalled flits.
* **`functionalRead(Packet *pkt, WriteMask &mask)` / `functionalWrite(Packet *)`:** Allows the gem5 simulator to inspect or modify packet data instantaneously without timing side-effects (used for debugging and checkpointing).


* **`scheduleFlit(flit *t_flit)`:** Schedules a flit for transmission over an output link based on link latency.
* **`print(std::ostream& out)`:** Prints NI state for debugging.

#### Vnet, Routing & VC Helpers

* **`get_vnet(int vc)`:** Maps a specific Virtual Channel index to its parent Virtual Network (Vnet) to prevent protocol-level deadlocks.
* **`get_router_id(int vnet)`:** Returns the router ID connected to the output port supporting a given Vnet.
* **`MachineType_base_number(const MachineType& obj)`:** Determines the base node ID for different coherence machine types (e.g., L1, L2, Directory).

---

### Private Helper & Pipeline Functions

* **`flitisizeMessage(MsgPtr msg_ptr, int vnet)`:** Converts a protocol `Message` into individual `flit` packets sized according to link bit-widths.
* **`calculateVC(int vnet)`:** Allocates an available Virtual Channel within the specified Vnet for an outgoing message.
* **`scheduleOutputPort(OutputPort *oPort)` / `scheduleOutputLink()`:** Arbitrates and schedules flits to move from the NI flit buffers onto the physical network links.
* **`checkStallQueue()`:** Re-evaluates flits waiting in `m_stall_queue` when space becomes available in the protocol message buffers.
* **`checkReschedule()`:** Re-schedules the NI to wake up on the next cycle if unsent flits or credits remain.
* **`incrementStats(flit *t_flit)`:** Updates simulation statistics (latency, hops, packet counts).
* **`getInportForVnet(int vnet)` / `getOutportForVnet(int vnet)`:** Finds the specific physical input or output port that routes traffic for a given virtual network.



----------------------------------------------------------
2> configs/network/Network.py
ls configs/topologies/
Every hardware parameter exposed to the C++ implementation is declared in the src/mem/ruby/network/ .py files. These define default values and data types:
3>./build/X86/gem5.opt configs/example/garnet_synth_traffic.py --help
-------------------------
task 3 week 4>
1 and 2 are in their python scripts
3> cyclestoticks = cycles * (fsim/fclk).




It is completely understandable to feel overwhelmed by how these components link together; the architecture is heavily layered. Let's map out the hierarchy and connections of these classes in the **GEM5** simulator to clarify the flow of data.

### 1. The Injection/Ejection Boundary

This layer converts abstract protocol messages into physical network traffic.

* **`MessageBuffer`**: These are the queues that act as the interface between the SLICC cache/directory controllers and the NoC. Packets are buffered here before entering the network.


* **`NetworkInterface` (NI)**: This acts as the bridge between the memory controllers and the NoC. It dequeues messages from the memory system, breaks them into packets/flits, and injects them into the network.



### 2. The Router Microarchitecture

Once flits leave the NI, they enter the detailed Garnet NoC routers.

* **`Router`**: The main router class orchestrates the internal pipeline required to transmit a packet to its next hop, handling routing, switch allocation, and VC allocation.


* **`InputUnit`**: Connected to incoming wires. It receives flits from a neighboring router or NI, stores them in Virtual Channel (VC) buffers, and initiates the router's pipeline arbitration.
* **`OutputUnit`**: Manages the router's output ports. After a flit crosses the internal crossbar switch, this unit wakes up the connected `NetworkLink` to physically transmit the flit to the next node.



### 3. The Physical Interconnect & Data

These classes represent the global view and physical wires connecting the components.

* **`GarnetNetwork`**: The top-level manager object. It instantiates and holds pointers to all the NIs, Routers, and Links based on the Python topology configuration.
* **`NetworkLink`**: Models the physical wires themselves. It handles the actual transmission delay and bandwidth constraints as flits travel from one router to another.


* **`flit`**: The fundamental data structure. Since packets are transmitted flit-by-flit in a realistic NoC, this object contains the properties of the transmission unit (like VC allocation and timestamp).
