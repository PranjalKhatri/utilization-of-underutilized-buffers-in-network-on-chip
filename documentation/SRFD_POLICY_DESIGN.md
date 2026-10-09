# Policy-based SRFD admission, storage and eviction

**Status: design proposal for review.** The policies and flags described below
are not implemented. Current experiments continue using the existing admission,
placement and oldest-victim behavior. This proposal does not replace the
escape path, change coherence messages or modify running experiments.

## 1. Separate the decisions

The word "policy" covers three different questions:

| Decision | Question | Proposed first version |
|---|---|---|
| Admission | Is this new block worth retaining? | Always attempt, or consult reuse history |
| Placement | Which safe buffer should hold it? | Preserve Local preference and existing directional lease selection |
| Victim selection | Which retained block should leave? | Oldest, or lowest predicted reuse score |

These decisions must be separate from the mechanisms that move flits, return
credits, acquire leases, drop clean blocks and forward dirty blocks.

Current insertion occurs in `InputUnit::wakeup()`. Local pressure and
directional reclaim choose complete victims using `oldestStored()`.
`Router::trySpill()` chooses directional destinations, while `releaseSrfd()`
performs the actual removal. The new policy layer would supply admission and
victim decisions to those paths rather than duplicate their bookkeeping.

## 2. Proposed policy interface

Create one policy coordinator per router, shared by all its storage inputs.
Local-only mode uses the same interface with its smaller eligible scope.

```cpp
struct Candidate {
    Addr address;
    bool dirty;
    Tick offeredAt;
};

struct ResidentView {
    Addr address;
    bool dirty;
    int inputPort;
    int vc;
    uint64_t sequence;  // identity and oldest-first ordering
};

struct PressureContext {
    int affectedInput;
    int vnet;
    bool mandatoryReclaim;
};

AdmissionDecision considerAdmission(const Candidate &candidate);
optional<ResidentView> chooseVictim(
    const vector<ResidentView> &eligible,
    const PressureContext &context);

void onAdmission(Addr address, bool dirty);
void onHit(Addr address);
void onDeparture(Addr address, bool dirty, DepartureReason reason);
void onRequest(Addr address, RequestKind kind, Tick now);
void onBypass(Addr address, bool dirty, Tick now);
```

The mechanism constructs the eligible list. A policy cannot choose incomplete,
transferring, already-releasing or escape-buffer entries. Returned decisions
include the sequence identity; revalidate it before applying a decision that
was delayed by a lookup or asynchronous action. Retry selection if the entry
was hit or removed in the meantime.

Callbacks are observations, not permission to change coherence state or
credit/lease ownership. Internal migration preserves address, age and history;
it is not a new admission, eviction or successful reuse.

## 3. First concrete history policy

Use a bounded, four-way set-associative table with **256 entries per router**
and physical cache-line addresses as keys. Index 64 sets using a folded line
address hash and compare the full stored tag to distinguish collisions.
Replace history entries with per-set LRU. Losing a history entry loses only
prediction information, not its actual retained block or coherence state.

Each entry records:

- A valid tag and a 3-bit saturating score, 0-7.
- Optional departure/bypass timestamp and the departing block's dirty flag.
- An aging epoch and replacement metadata.

The simulator can use full-width timestamps. Hardware compression needs
separate wrap/expiry handling and an area calculation. A few hundred entries
are already more metadata than the current per-VC retention tags, so report
table cost rather than treating history as free.

Suggested initial rules:

| Observation | Score update |
|---|---|
| Previously unseen address | Initialize to 3, a neutral score |
| Successful clean or dirty SRFD hit | Add 2, saturating at 7 |
| Pressure/policy eviction without a hit | Subtract 1, saturating at 0 |
| First useful re-reference within 50,000 cycles of departure/bypass | Add 2 |
| Later re-reference | Consume the pending observation without a bonus |
| Duplicate-clean cleanup or clean GETX conflict | Do not apply the pressure/policy-eviction penalty |

For a departed clean block, a GETX is not a useful SRFD-reply opportunity:
clean storage cannot serve GETX. Do not reward that shadow observation as if
it could have supplied the request. A dirty block can serve eligible GETS or
GETX. Existing coherence eligibility checks still determine actual hits.

Record at most one pending departure/bypass observation per address, using
the most recent timestamp. Clear that pending observation on re-admission to
avoid rewarding both an old departure and a hit on the new retained copy.
This predictor bookkeeping is separate from existing statistical tracking,
whose definitions remain unchanged.

Age scores lazily toward neutral 3 by one step per **4,096 eligible request
lookups per router**. Store the last updated epoch and apply the elapsed decay
when an entry is consulted, avoiding a scan/write of the entire table in one
cycle. Retries of the same waiting request must not advance the request count
or train history again.

These sizes, weights and thresholds are engineering starting points, not
paper parameters or established optimal settings.

### Learning from rejected blocks

A predictor must not permanently exclude a low-scoring block and therefore
never learn that it became useful. Track a shadow timestamp when admission
rejects a candidate. A later useful eligible request can raise its score even
though the block was not physically stored.

Additionally, admit one in every 32 otherwise-rejected candidates as a
deterministic exploration probe when safe free retention capacity exists.
Probes do not evict a resident or override mandatory pressure. Use a separate
policy counter rather than the simulator's random generator, preserving
reproducibility and avoiding changes to unrelated randomization.

## 4. Admission and storage flow

For history admission, the initial admission threshold is **score >= 2**.
Cold addresses with neutral score 3 therefore get a chance to demonstrate
reuse. Policies never bypass the existing eligibility tests for clean/dirty
storage or packet-size checks.

```text
Eligible eviction offered
    |
    +-- Policy rejects --> clean: assemble and drop
    |                     dirty: ordinary writeback without retention
    |
    +-- Policy accepts --> Local retention room exists? --> retain locally
                          |
                          +-- otherwise try directional placement,
                              when enabled, using existing safe leases
                          |
                          +-- no destination available:
                              consider replacement within Local input;
                              otherwise use existing bypass fallback
```

A policy-rejected dirty block must still reach memory. A rejected clean
candidate uses the existing clean-bypass handling; it must not be sent as an
unexpected clean writeback to the memory directory. Retain the normal
pending-store and tail-assembly rules for either path.

For the initial history admission implementation, proactive replacement is
limited to the candidate's Local input. If it already has a staging VC and
its score is strictly greater than the selected resident's score, release
that resident through the existing mechanism and admit the candidate into
its own VC when the retention count permits. Otherwise bypass it. Do not
overwrite the victim's flits or assume a dirty release frees physical space
instantaneously.

When admission is `always`, preserve the existing placement/fallback behavior;
do not silently add proactive replacement to the legacy path. History
replacement used together with history admission ranks victims as below.
With oldest replacement selected, the admission comparison uses the existing
oldest victim's history score.

If all ordinary Local VCs are busy, the packet may not reach the admission
point yet. NI pressure recovery still has to make progress. Filtering
admission at the router does not magically avoid injection traffic or all
Local stalls; early filtering at the producer/NI would be a separate extension.

## 5. Victim selection and physical pressure

History replacement sorts eligible victims by:

```text
lowest reuse score, then clean before dirty, then oldest sequence
```

Score is the primary criterion. The clean tie-break prefers an immediate
drop over a writeback when predicted usefulness is equal. Dirty victims keep
their existing escape-routing and data-preservation requirements.

Mandatory pressure has a **physical scope**:

| Trigger | Eligible victim scope | Required outcome |
|---|---|---|
| Local NI allocation failure | Affected Local input and vnet | Free its injection capacity through existing migration/release |
| Neighbour reclaim for East | East input and affected vnet | Empty a leased East VC and return that lease |
| Neighbour reclaim for West/North/South | Corresponding input and vnet | Empty a VC in that input |

Even if every score is high, mandatory reclaim chooses a valid victim. It
cannot wait indefinitely for a low score. If entries are transferring or
already draining, use existing completion/retry handling rather than selecting
them a second time.

Evicting a lower-scoring West block alone cannot relieve East pressure. A
future global policy could free West and relocate an East block there, but
that requires another safely allocated destination, transfer arbitration and
bounded pressure handling. It is not included in the first version.

### Example: admitting a valuable new block

Local stores A(score 6), B(score 1), C(score 3), D(score 2). New X has score 5,
arrives in a staging VC, and no directional destination is available. History
replacement selects B, even if D is older. If B is dirty, it is forwarded
safely; X is not allowed to overwrite it. X can be retained in its existing
staging VC once the retained-count limit permits.

### Example: reclaiming East

East contains E1(score 6, dirty), E2(score 1, clean), E3(score 3, dirty), and
E4(score 2, clean). West contains an even lower-scoring W1(score 0).
An East reclaim chooses **E2**, drops it and returns its East lease. W1 is
outside the eligible scope; selecting it would not satisfy the neighbour.

## 6. Code integration and proposed flags

Put the reusable policy/coordinator alongside Garnet router support, with
Router owning its lifetime. Call admission from the eligible-store path,
victim selection from Local pressure and directional reclaim, and feedback
from successful hits, actual departures and first eligible request arrivals.
Router-wide placement/indexing remains the existing mechanism.

Pass departure reason explicitly: pressure, policy replacement, duplicate
cleanup, clean-GETX conflict or bypass. The current generic `releaseSrfd()`
drop/forward choice alone is insufficient for different learning updates.

Proposed flags, **not currently accepted by gem5**:

```text
--srfd-admission-policy=always|history       default: always
--srfd-eviction-policy=oldest|history        default: oldest
--srfd-history-entries=256                  power-of-two sets, four ways
--srfd-history-reuse-threshold=50000         router cycles
--srfd-history-admission-threshold=2
--srfd-policy-lookup-latency=1               router cycle for history decisions
```

The default combination allocates no history table and must preserve current
timing/actions exactly. If either policy uses history, enable its feedback
and bounded table. Charge decision latency for admission/victim decisions;
do not introduce a perfect zero-cost oracle. Coalesce pending pressure
decisions and revalidate the victim after the lookup delay.

These flags are independent of `--srfd-directional-storage`, operating mode
and retention cap. History never unlocks escape VCs or creates a cap-6
directional configuration with six physical VCs.

History persists through an ordinary statistics reset so warmup can train it;
only measurement counters reset. Active-SRFD checkpoint restrictions stay in
force. Restore the same cold baseline checkpoint and use the same warmup
convention for every comparison.

## 7. Instrumentation and evaluation

Add separate policy-table lookups/hits/misses, metadata replacements,
admission accepts/rejects, exploration probes, useful shadow re-references,
policy replacements, clean/dirty victim selections and decision-wait cycles.
Policy-table hit rate is not the SRFD local-reply rate.

Keep existing offer/admit/bypass/resident and lease accounting. Partition
policy and capacity bypass reasons without counting either twice. A rejected
candidate was never retained, so it is not an actual SRFD eviction and must
not inflate the existing post-SRFD-eviction statistic. Shadow predictions get
their own counters.

Compare four combinations with identical topology, caps, memory, escape
reservation, checkpoint and instruction budgets:

1. Always admit + oldest replacement: preserved reference.
2. Always admit + history replacement: isolate victim selection.
3. History admission + oldest replacement: isolate admission filtering.
4. History admission + history replacement: combined policy.

Report IPC, LLC penalty, eligible-request hit rates, clean/dirty replies,
store-to-hit time, missed-reuse intervals, occupancy, pressure, directional
transfers/reclaims and table/lookup cost. Higher hit rate alone is insufficient:
the current cap-5 results already show that latency benefit can be outweighed
by buffer contention.

Validate bounded metadata/collisions, aging, cold starts and exploration;
clean GETX handling; delayed decisions racing with hits/reclaim; required
pressure release despite high scores; incomplete entries; DIR lease balance;
and statistics resets. Run data-checking randomized tests and small O3 FS
tests before changing long experiments. Keep audits and generated results in
`PAPER_TESTS`.

Possible later extensions include page-based signatures, measured
reuse-distance prediction and relocation to protect valuable victims.
Prefetching adds a separate traffic/coherence operation and should not be
silently mixed into the initial retention policy.
