# Why directional SRFD uses an escape VC

This document describes the implemented directional-storage design. Its
escape VC is a protected network path for released dirty blocks and SRFD
replies. It is one way to preserve progress when ordinary input VCs can be
borrowed for storage; it is not an inherent requirement of every possible
router-buffer caching design.

## Input buffers, output state and reservations

L, E, W, N and S refer to **input** buffers. A's East input receives normal
packets from its eastern neighbour B. If A borrows that buffer, the retained
block is still physically inside A.

```text
B's West output allocation/credits  -->  A's East input buffers
                                        Actual retained data lives here.
```

B's output VC state tracks space in A. Leasing an A input VC prevents B from
sending into that VC; it does not consume a physical input buffer inside B.
The lease is separate from ordinary credits, which remain unchanged because
B did not inject the locally stored packet.

With six VCs per data vnet, the implemented reservation is:

| Retention cap per input | VCs eligible for retention | Ordinary-data headroom | Escape VC |
|---|---|---|---|
| 4 | At most four of VC 0-4 | One VC excluded from persistent retention | VC 5 |
| 5 | At most five of VC 0-4 | None protected from persistent retention | VC 5 |

There is **one escape VC, not two**. Cap 4 also leaves ordinary-data headroom.
Normal traffic and packets already draining can temporarily occupy that
headroom. The cap applies to Local and every existing directional storage
input. VC 5 is protected on every data input, including non-storage inputs;
ordinary data injection/allocation excludes it in feature-enabled runs.
Absent edge/corner directions do not acquire additional buffers.

## Example 1: a circular wait without an escape path

Consider adjacent routers A and B. Suppose every ordinary VC of A's East
input and B's West input is leased for retained dirty blocks. A has a victim
that needs to travel east through B; B has a victim that needs to travel west
through A. Their final memory destinations can be farther along those routes.

```text
A's East retained block  --> needs an available B West input VC
B's West retained block  --> needs an available A East input VC
```

1. A cannot allocate B's West input: its ordinary VCs are leased by B.
2. B cannot allocate A's East input: its ordinary VCs are leased by A.
3. A cannot return its victim's lease until the dirty packet leaves its buffer.
4. B cannot return its victim's lease until its dirty packet leaves its buffer.

Both dirty copies must be preserved, so neither can simply discard its victim.
Selecting the oldest block does not create the missing transmission capacity.
This is a circular resource dependency. Clean victims could be dropped to
break it, but a design must also handle the all-dirty case.

With escape VC 5, A can allocate B's West escape buffer, and B can allocate A's
East escape buffer. These are distinct physical buffers that neither router
can lease for retention. Released packets can drain even when ordinary VCs
are borrowed. Escape buffers still obey credits and may wait behind other
escape packets; they do not guarantee immediate delivery.

## Example 2: why the packet stays on escape VCs

A released block remains an ordinary coherence writeback or reply in meaning.
The extra classification controls network allocation, not its protocol type.

If it used an escape VC only for its first hop, the next step could be:

```text
A --> B's escape input --> waits for C's leased ordinary input
```

The packet would hold an escape resource while waiting for ordinary storage
to be reclaimed. Those reclamations may themselves need escape resources.
Allowing this dependency removes the protection established by the separate
path; it does not mean every such packet would deadlock, but it permits the
problem to return.

The implementation therefore marks every flit of a released packet as escape
traffic and keeps it on VC 5 of the same data vnet at subsequent hops. These
VCs are never retained or leased, and their routes follow XY. Under the usual
XY routing, fair-arbitration and eventual-ejection assumptions, the protected
subnetwork avoids the storage dependencies described above. This is not a
claim that every possible coherence configuration is formally deadlock-free.

## Example 3: stored in East, released through North

Storage location and outgoing direction are independent. Borrowing A's East
buffer does not make the packet originate at the eastern neighbour or require
it to leave east.

Use the current 4x4 mesh numbering:

- A is router 4 at coordinates (0, 1).
- Its eastern neighbour is router 5 at (1, 1).
- Its northern neighbour is router 8 at (0, 2).
- The destination directory is at router 12 at (0, 3).

Suppose an eviction from A's local LLC has been stored in **A's East input,
VC 2**. Its original writeback destination remains the directory at router 12.

```text
                     Router 12: directory
                     South input, escape VC 5
                              ^
                              | Northward link
                     Router 8: South input, escape VC 5
                              ^
                              | A's North output
                  +-----------------------------+
                  | A = router 4                |
                  | East input VC 2             | <-- normal ingress from
                  |     retained dirty block    |     eastern router 5
                  |             |               |
                  |          crossbar --> North |
                  +-----------------------------+
```

The release proceeds as follows:

1. Remove the block from the retained-address index and mark all its flits as
   escape traffic. The flits remain in A's East input; there is no preliminary
   copy to A's Local or North input buffer.
2. Recompute the route using the original destination and **logical Local
   injection**. The destination has the same X coordinate and a larger Y
   coordinate, so XY selects A's North output.
3. A's North output allocates VC 5 at router 8's South input and checks its
   credits. The output's allocation state represents that downstream buffer.
4. Switch arbitration reads the actual flits from A's **East** input and
   connects that physical input to the **North** output through the crossbar.
5. When the tail leaves A's East buffer, that buffer becomes empty. A sends a
   lease-release notification to eastern router 5, which can later resume
   ordinary injection into A's East VC 2. No ordinary credits are returned to
   router 5 for these locally transferred flits.
6. Router 8 receives a normal link-transmitted escape packet in its South
   input. It uses the actual South arrival direction for the next XY decision
   and sends north using router 12's South escape VC.
7. At router 12, routing selects the directory's Local output. Credits for
   these link-transmitted flits return normally to the upstream sender as
   input slots are consumed/freed.

Two independent flow-control operations occur at A: the East storage lease
returns to router 5, while North transmission consumes credits for router 8's
South escape buffer. The packet does not travel through router 5.

### Why routing says Local while arbitration reads East

The packet originally came from A's local LLC and has not travelled through
the East link. Its physical East storage slot is therefore not its routing
history. `markEscape()` calls route computation with direction `Local`, while
the allocator continues to use the real input port and VC containing the data.

East-to-North happens to be permitted by the ordinary XY turn checks too.
The logical-Local treatment is needed consistently for other storage/output
combinations: for example, treating a locally stored East-buffer packet as a
real arrival from East would incorrectly reject sending it east toward its
original destination. Once it has taken a network hop, actual arrival
directions apply normally.

## Example 4: a hit changes the destination

The North example above is a dirty writeback release. A successful SRFD hit
has a different destination: the implementation rewrites the retained packet
as a reply to its original LLC controller.

For a block stored in A's East buffer, this normally means:

```text
A's East input --> A's crossbar --> Local output for A's LLC controller
```

It does not continue toward the original memory directory. The routing table
selects the exact Local output because several controllers may attach to one
router. The existing LLC reply/CAN_PUT path then handles coherence. A clean
block removed by pressure is simply dropped; it produces no northbound memory
writeback.

## How this differs from Local-only release

A Local input is an injection buffer. Ordinary inter-router transit packets
do not require that buffer as their next-hop directional resource. A
Local-only dirty release starts an ordinary XY route from there.

Directional borrowing changes the dependency structure: a retained packet
occupies a buffer that a neighbouring router needs for transmission. Its
release can also request another borrowed directional buffer. The escape
path separates that draining dependency from retained ordinary channels.

Moving victims back to Local, swapping blocks, or changing replacement policy
are possible alternative designs, but they need an explicit progress rule.
A Local staging slot can itself be full of a packet waiting for a leased
downstream buffer. Position/age policy alone does not solve that dependency.

## Implementation references

- `src/mem/ruby/network/garnet/InputUnit.cc`: `releaseSrfd()`, `markEscape()`,
  `trySrfdRequest()` and lease-aware `increment_credit()`.
- `src/mem/ruby/network/garnet/OutputUnit.cc`: ordinary/escape VC allocation
  and lease bookkeeping.
- `src/mem/ruby/network/garnet/SwitchAllocator.cc`: allocation class selection
  and actual input-to-output crossbar arbitration.
- `src/mem/ruby/network/garnet/RoutingUnit.cc`: local-destination selection
  and XY direction checks.

See [DIRECTIONAL_SRFD.md](DIRECTIONAL_SRFD.md) for flags, timing assumptions,
capacity and experiment commands.
