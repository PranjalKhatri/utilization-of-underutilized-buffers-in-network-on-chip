/*
 * Copyright (c) 2020-2021 ARM Limited
 * All rights reserved
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
 *
 * Copyright (c) 1999-2012 Mark D. Hill and David A. Wood
 * Copyright (c) 2013 Advanced Micro Devices, Inc.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#include "mem/ruby/structures/CacheMemory.hh"

#include <algorithm>

#include "base/intmath.hh"
#include "base/logging.hh"
#include "debug/HtmMem.hh"
#include "debug/RubyCache.hh"
#include "debug/RubyCacheTrace.hh"
#include "debug/RubyResourceStalls.hh"
#include "debug/RubyStats.hh"
#include "mem/cache/replacement_policies/weighted_lru_rp.hh"
#include "mem/ruby/protocol/AccessPermission.hh"
#include "mem/ruby/system/RubySystem.hh"
//////////////////////PRANJAL
using namespace std;
//////////////////////PRANJAL

namespace gem5
{

namespace ruby
{

std::ostream&
operator<<(std::ostream& out, const CacheMemory& obj)
{
    obj.print(out);
    out << std::flush;
    return out;
}

CacheMemory::CacheMemory(const Params &p)
    : SimObject(p),
    dataArray(p.dataArrayBanks, p.dataAccessLatency, p.start_index_bit),
    tagArray(p.tagArrayBanks, p.tagAccessLatency, p.start_index_bit),
    atomicALUArray(p.atomicALUs, p.atomicLatency),
    cacheMemoryStats(this, p.top_n_set, p.max_re_reference_cycles)
{
    m_cache_size = p.size;
    m_cache_assoc = p.assoc;
    //PRANJAL
    m_print_evictions = p.print_evictions;
    m_top_n_set = p.top_n_set;
    m_max_re_reference_cycles = p.max_re_reference_cycles;
    m_last_accessed_address = 0;
    //PRANJAL
    m_replacementPolicy_ptr = p.replacement_policy;
    m_start_index_bit = p.start_index_bit;
    m_is_instruction_only_cache = p.is_icache;
    m_resource_stalls = p.resourceStalls;
    m_block_size = p.block_size;  // may be 0 at this point. Updated in init()
    m_use_occupancy = dynamic_cast<replacement_policy::WeightedLRU*>(
                                    m_replacementPolicy_ptr) ? true : false;
}

void
CacheMemory::resetStats()
{
    SimObject::resetStats();
    m_re_reference_cycle.clear();
    m_llc_miss_start_cycle.clear();
    cacheMemoryStats.m_tracked_re_reference_addresses = 0;
}

void
CacheMemory::setRubySystem(RubySystem* rs)
{
    dataArray.setClockPeriod(rs->clockPeriod());
    tagArray.setClockPeriod(rs->clockPeriod());
    atomicALUArray.setClockPeriod(rs->clockPeriod());
    atomicALUArray.setBlockSize(rs->getBlockSizeBytes());

    if (m_block_size == 0) {
        m_block_size = rs->getBlockSizeBytes();
    }

    m_ruby_system = rs;
}

void
CacheMemory::init()
{
    assert(m_block_size != 0);
    m_cache_num_sets = (m_cache_size / m_cache_assoc) / m_block_size;
    assert(m_cache_num_sets > 1);
    m_cache_num_set_bits = floorLog2(m_cache_num_sets);
    assert(m_cache_num_set_bits > 0);

    //PRANJAL
    if (m_top_n_set > 0) {
        m_set_access_counts.resize(m_cache_num_sets, 0);
    }
    
    // Initialize hits/misses per set and per way statistics with actual cache dimensions
    // cacheMemoryStats.hits_per_set.init(m_cache_num_sets);
    // cacheMemoryStats.misses_per_set.init(m_cache_num_sets);
    // cacheMemoryStats.hits_per_way.init(m_cache_assoc);
    // cacheMemoryStats.misses_per_way.init(m_cache_assoc);
    cacheMemoryStats.hits_per_set.init(1);//PRANJAL disabled for less clutter in stats output
    cacheMemoryStats.misses_per_set.init(1);
    cacheMemoryStats.hits_per_way.init(1);
    cacheMemoryStats.misses_per_way.init(1);
    //PRANJAL

    m_cache.resize(m_cache_num_sets,
                    std::vector<AbstractCacheEntry*>(m_cache_assoc, nullptr));
    replacement_data.resize(m_cache_num_sets,
                               std::vector<ReplData>(m_cache_assoc, nullptr));
    // instantiate all the replacement_data here
    for (int i = 0; i < m_cache_num_sets; i++) {
        for ( int j = 0; j < m_cache_assoc; j++) {
            replacement_data[i][j] =
                                m_replacementPolicy_ptr->instantiateEntry();
        }
    }
}

CacheMemory::~CacheMemory()
{
    if (m_replacementPolicy_ptr)
        delete m_replacementPolicy_ptr;
    for (int i = 0; i < m_cache_num_sets; i++) {
        for (int j = 0; j < m_cache_assoc; j++) {
            delete m_cache[i][j];
        }
    }
}

// convert a Address to its location in the cache
int64_t
CacheMemory::addressToCacheSet(Addr address) const
{
    assert(address == makeLineAddress(address));
    return bitSelect(address, m_start_index_bit,
                     m_start_index_bit + m_cache_num_set_bits - 1);
}

// Given a cache index: returns the index of the tag in a set.
// returns -1 if the tag is not found.
int
CacheMemory::findTagInSet(int64_t cacheSet, Addr tag) const
{
    assert(tag == makeLineAddress(tag));
    // search the set for the tags
    auto it = m_tag_index.find(tag);
    if (it != m_tag_index.end())
        if (m_cache[cacheSet][it->second]->m_Permission !=
            AccessPermission_NotPresent)
            return it->second;
    return -1; // Not found
}

// Given a cache index: returns the index of the tag in a set.
// returns -1 if the tag is not found.
int
CacheMemory::findTagInSetIgnorePermissions(int64_t cacheSet,
                                           Addr tag) const
{
    assert(tag == makeLineAddress(tag));
    // search the set for the tags
    auto it = m_tag_index.find(tag);
    if (it != m_tag_index.end())
        return it->second;
    return -1; // Not found
}

// Given an unique cache block identifier (idx): return the valid address
// stored by the cache block.  If the block is invalid/notpresent, the
// function returns the 0 address
Addr
CacheMemory::getAddressAtIdx(int idx) const
{
    Addr tmp(0);

    int set = idx / m_cache_assoc;
    assert(set < m_cache_num_sets);

    int way = idx - set * m_cache_assoc;
    assert (way < m_cache_assoc);

    AbstractCacheEntry* entry = m_cache[set][way];
    if (entry == NULL ||
        entry->m_Permission == AccessPermission_Invalid ||
        entry->m_Permission == AccessPermission_NotPresent) {
        return tmp;
    }
    return entry->m_Address;
}

bool
CacheMemory::tryCacheAccess(Addr address, RubyRequestType type,
                            DataBlock*& data_ptr)
{
    DPRINTF(RubyCache, "trying to access address: %#x\n", address);
    AbstractCacheEntry* entry = lookup(address);
    if (entry != nullptr) {
        // Do we even have a tag match?
        m_replacementPolicy_ptr->touch(entry->replacementData);
        entry->setLastAccess(curTick());
        data_ptr = &(entry->getDataBlk());

        if (entry->m_Permission == AccessPermission_Read_Write) {
            DPRINTF(RubyCache, "Have permission to access address: %#x\n",
                        address);
            return true;
        }
        if ((entry->m_Permission == AccessPermission_Read_Only) &&
            (type == RubyRequestType_LD || type == RubyRequestType_IFETCH)) {
            DPRINTF(RubyCache, "Have permission to access address: %#x\n",
                        address);
            return true;
        }
        // The line must not be accessible
    }
    DPRINTF(RubyCache, "Do not have permission to access address: %#x\n",
                address);
    data_ptr = NULL;
    return false;
}

bool
CacheMemory::testCacheAccess(Addr address, RubyRequestType type,
                             DataBlock*& data_ptr)
{
    DPRINTF(RubyCache, "testing address: %#x\n", address);
    AbstractCacheEntry* entry = lookup(address);
    if (entry != nullptr) {
        // Do we even have a tag match?
        m_replacementPolicy_ptr->touch(entry->replacementData);
        entry->setLastAccess(curTick());
        data_ptr = &(entry->getDataBlk());

        DPRINTF(RubyCache, "have permission for address %#x?: %d\n",
                    address,
                    entry->m_Permission != AccessPermission_NotPresent);
        return entry->m_Permission != AccessPermission_NotPresent;
    }

    DPRINTF(RubyCache, "do not have permission for address %#x\n",
                address);
    data_ptr = NULL;
    return false;
}

// tests to see if an address is present in the cache
bool
CacheMemory::isTagPresent(Addr address) const
{
    const AbstractCacheEntry* const entry = lookup(address);
    if (entry == nullptr) {
        // We didn't find the tag
        DPRINTF(RubyCache, "No tag match for address: %#x\n", address);
        return false;
    }
    DPRINTF(RubyCache, "address: %#x found\n", address);
    return true;
}

// Returns true if there is:
//   a) a tag match on this address or there is
//   b) an unused line in the same cache "way"
bool
CacheMemory::cacheAvail(Addr address) const
{
    assert(address == makeLineAddress(address));

    int64_t cacheSet = addressToCacheSet(address);

    for (int i = 0; i < m_cache_assoc; i++) {
        AbstractCacheEntry* entry = m_cache[cacheSet][i];
        if (entry != NULL) {
            if (entry->m_Address == address ||
                entry->m_Permission == AccessPermission_NotPresent) {
                // Already in the cache or we found an empty entry
                return true;
            }
        } else {
            return true;
        }
    }
    return false;
}

AbstractCacheEntry*
CacheMemory::allocate(Addr address, AbstractCacheEntry *entry)
{
    assert(address == makeLineAddress(address));
    assert(!isTagPresent(address));
    assert(cacheAvail(address));
    DPRINTF(RubyCache, "allocating address: %#x\n", address);


        //PRANJAL
    // --- PAPER IMPLEMENTATION: Calculate Re-reference Latency ---
    const uint64_t current_cycle = m_ruby_system->curCycle();
    auto it = m_re_reference_cycle.find(address);
    if (it != m_re_reference_cycle.end()) {
        const uint64_t cycles = current_cycle - it->second;

        if (cycles > 0) {
            cacheMemoryStats.m_total_re_reference_cycles += cycles;
            cacheMemoryStats.m_total_re_references++;
            cacheMemoryStats.m_re_reference_cycles.sample(cycles);
        }
        if (cycles > m_max_re_reference_cycles) {
            cacheMemoryStats.m_re_reference_histogram_overflows++;
        }

        // Retain the address and begin a new interval for every observation.
        it->second = current_cycle;
    }
    // ------------------------------------------------------------
    //PRANJAL

    entry->initBlockSize(m_block_size);
    entry->setRubySystem(m_ruby_system);

    // Find the first open slot
    int64_t cacheSet = addressToCacheSet(address);
    std::vector<AbstractCacheEntry*> &set = m_cache[cacheSet];
    for (int i = 0; i < m_cache_assoc; i++) {
        if (!set[i] || set[i]->m_Permission == AccessPermission_NotPresent) {
            if (set[i] && (set[i] != entry)) {
                warn_once("This protocol contains a cache entry handling bug: "
                    "Entries in the cache should never be NotPresent! If\n"
                    "this entry (%#x) is not tracked elsewhere, it will memory "
                    "leak here. Fix your protocol to eliminate these!",
                    address);
            }
            set[i] = entry;  // Init entry
            set[i]->m_Address = address;
            set[i]->m_Permission = AccessPermission_Invalid;
            DPRINTF(RubyCache, "Allocate clearing lock for addr: 0x%x\n",
                    address);
            set[i]->m_locked = -1;
            m_tag_index[address] = i;
            set[i]->setPosition(cacheSet, i);
            set[i]->replacementData = replacement_data[cacheSet][i];
            set[i]->setLastAccess(curTick());

            // Call reset function here to set initial value for different
            // replacement policies.
            m_replacementPolicy_ptr->reset(entry->replacementData);

            return entry;
        }
    }

    panic("Allocate didn't find an available entry");
}

void
CacheMemory::deallocate(Addr address)
{
    DPRINTF(RubyCache, "deallocating address: %#x\n", address);
    //PRANJAL
    if (m_print_evictions)
        cacheMemoryStats.numEvictions++;
    // --- PAPER IMPLEMENTATION: Record Eviction Cycle ---
    m_re_reference_cycle[address] = m_ruby_system->curCycle();
    cacheMemoryStats.m_tracked_re_reference_addresses =
        m_re_reference_cycle.size();
    // ---------------------------------------------------
    //PRANJAL
    AbstractCacheEntry* entry = lookup(address);
    assert(entry != nullptr);
    m_replacementPolicy_ptr->invalidate(entry->replacementData);
    uint32_t cache_set = entry->getSet();
    uint32_t way = entry->getWay();
    delete entry;
    m_cache[cache_set][way] = NULL;
    m_tag_index.erase(address);
}

//PRANJAL
void
CacheMemory::recordSetAccess(Addr address)
{
    // Store the address for later use in profileDemandHit/Miss
    m_last_accessed_address = address;
    
    if (m_top_n_set <= 0 || m_set_access_counts.empty()) {
        return;
    }

    int64_t set = addressToCacheSet(address);
    if (set >= 0 && set < static_cast<int64_t>(m_set_access_counts.size())) {
        m_set_access_counts[set]++;
        updateTopNSetAccesses();
    }
}

void
CacheMemory::updateTopNSetAccesses()
{
    //PRANJAL disable for now
    // if (m_top_n_set <= 0 || m_set_access_counts.empty()) {
    //     return;
    // }

    // std::vector<std::pair<int, uint64_t>> ranked_sets;
    // ranked_sets.reserve(m_set_access_counts.size());
    // for (int set = 0; set < static_cast<int>(m_set_access_counts.size()); ++set) {
    //     ranked_sets.emplace_back(set, m_set_access_counts[set]);
    // }

    // std::sort(ranked_sets.begin(), ranked_sets.end(),
    //     [](const std::pair<int, uint64_t>& a,
    //        const std::pair<int, uint64_t>& b) {
    //         if (a.second != b.second) {
    //             return a.second > b.second;
    //         }
    //         return a.first < b.first;
    //     });

    // const int limit = std::min(m_top_n_set,
    //                           static_cast<int>(ranked_sets.size()));

    // for (int i = 0; i < limit; ++i) {
    //     cacheMemoryStats.topNSetIds[i] = ranked_sets[i].first;
    //     cacheMemoryStats.topNSetCounts[i] = ranked_sets[i].second;
    // }
}
//PRANJAL

//PRANJAL - Record hits/misses per set and per way as statistics
void
CacheMemory::recordHitWithAddress(Addr address)
{
    int64_t set = addressToCacheSet(address);
    if (set >= 0 && set < m_cache_num_sets) {
        //PRANJAL DISABLED
        // cacheMemoryStats.hits_per_set[set]++;
    }
    
    // Get the way by looking up the entry
    int loc = findTagInSet(set, address);
    if (loc >= 0 && loc < m_cache_assoc) {
        //PRANJAL DISABLED
        // cacheMemoryStats.hits_per_way[loc]++;
    }
}

void
CacheMemory::recordMissWithAddress(Addr address)
{
    int64_t set = addressToCacheSet(address);
    if (set >= 0 && set < m_cache_num_sets) {
        //PRANJAL DISABLED
        // cacheMemoryStats.misses_per_set[set]++;
    }
    
    // For misses, increment a generic way counter if possible
    // Note: We don't have a specific way for misses yet (way is determined during replacement)
    if (m_cache_assoc > 0) {
        //PRANJAL DISABLED
        // cacheMemoryStats.misses_per_way[0]++;  // Track all misses in way 0 for now
    }
}
//PRANJAL

// Returns with the physical address of the conflicting cache line
Addr
CacheMemory::cacheProbe(Addr address) const
{
    assert(address == makeLineAddress(address));
    assert(!cacheAvail(address));

    int64_t cacheSet = addressToCacheSet(address);
    std::vector<ReplaceableEntry*> candidates;
    for (int i = 0; i < m_cache_assoc; i++) {
        candidates.push_back(static_cast<ReplaceableEntry*>(
                                                       m_cache[cacheSet][i]));
    }
    return m_cache[cacheSet][m_replacementPolicy_ptr->
                        getVictim(candidates)->getWay()]->m_Address;
}

// Records the first off-chip issue cycle for this cache line.
void
CacheMemory::recordLlcMissStart(Addr address)
{
    address = makeLineAddress(address);
    const auto result = m_llc_miss_start_cycle.emplace(
        address, m_ruby_system->curCycle());
    // A duplicate start would silently retain an old timestamp.
    assert(result.second);
}

void
CacheMemory::beginSrfdStore(Addr address)
{
    m_ruby_system->beginSrfdStore(makeLineAddress(address));
}

void
CacheMemory::recordLlcMissComplete(Addr address, int source)
{
    address = makeLineAddress(address);
    auto it = m_llc_miss_start_cycle.find(address);
    if (it == m_llc_miss_start_cycle.end()) {
        ++cacheMemoryStats.m_llc_miss_untracked_completions;
        return;
    }
    const uint64_t cycles = m_ruby_system->curCycle() - it->second;
    m_llc_miss_start_cycle.erase(it);
    cacheMemoryStats.m_llc_miss_cycles.sample(cycles);
    cacheMemoryStats.m_llc_miss_total_cycles += cycles;
    ++cacheMemoryStats.m_llc_miss_count;
    if (source == 0) {
        cacheMemoryStats.m_llc_miss_memory_cycles.sample(cycles);
        cacheMemoryStats.m_llc_miss_memory_total_cycles += cycles;
        ++cacheMemoryStats.m_llc_miss_memory_count;
    } else if (source == 1) {
        cacheMemoryStats.m_llc_miss_dirty_local_cycles.sample(cycles);
        cacheMemoryStats.m_llc_miss_dirty_local_total_cycles += cycles;
        ++cacheMemoryStats.m_llc_miss_dirty_local_count;
    } else if (source == 2) {
        cacheMemoryStats.m_llc_miss_clean_local_cycles.sample(cycles);
        cacheMemoryStats.m_llc_miss_clean_local_total_cycles += cycles;
        ++cacheMemoryStats.m_llc_miss_clean_local_count;
    } else {
        panic("Invalid LLC miss completion source %d", source);
    }
}

void
CacheMemory::recordSrfdCleanCandidate()
{
    ++cacheMemoryStats.m_srfd_clean_candidates;
}



void
CacheMemory::recordSrfdCleanEmitted()
{
    ++cacheMemoryStats.m_srfd_clean_emitted;
}

void
CacheMemory::recordSrfdL1CleanExclusiveInstall()
{
    ++cacheMemoryStats.m_srfd_l1_clean_exclusive_installs;
}

void
CacheMemory::recordSrfdL1CleanReplacement()
{
    ++cacheMemoryStats.m_srfd_l1_clean_replacements;
}

void
CacheMemory::recordSrfdL1CleanWriteback()
{
    ++cacheMemoryStats.m_srfd_l1_clean_writebacks;
}

void
CacheMemory::recordSrfdCanPutSent(bool dirty)
{
    m_ruby_system->recordSrfdCanPutSent(dirty);
    if (dirty)
        ++cacheMemoryStats.m_srfd_can_put_dirty_sent;
    else
        ++cacheMemoryStats.m_srfd_can_put_clean_sent;
}

AbstractCacheEntry*
CacheMemory::lookup(Addr address)
{
    assert(address == makeLineAddress(address));
    int64_t cacheSet = addressToCacheSet(address);
    int loc = findTagInSet(cacheSet, address);
    if (loc == -1) return NULL;
    return m_cache[cacheSet][loc];
}

// looks an address up in the cache
const AbstractCacheEntry*
CacheMemory::lookup(Addr address) const
{
    assert(address == makeLineAddress(address));
    int64_t cacheSet = addressToCacheSet(address);
    int loc = findTagInSet(cacheSet, address);
    if (loc == -1) return NULL;
    return m_cache[cacheSet][loc];
}

// Sets the most recently used bit for a cache block
void
CacheMemory::setMRU(Addr address)
{
    AbstractCacheEntry* entry = lookup(makeLineAddress(address));
    if (entry != nullptr) {
        m_replacementPolicy_ptr->touch(entry->replacementData);
        entry->setLastAccess(curTick());
    }
}

void
CacheMemory::setMRU(AbstractCacheEntry *entry)
{
    assert(entry != nullptr);
    m_replacementPolicy_ptr->touch(entry->replacementData);
    entry->setLastAccess(curTick());
}

void
CacheMemory::setMRU(Addr address, int occupancy)
{
    AbstractCacheEntry* entry = lookup(makeLineAddress(address));
    if (entry != nullptr) {
        // m_use_occupancy can decide whether we are using WeightedLRU
        // replacement policy. Depending on different replacement policies,
        // use different touch() function.
        if (m_use_occupancy) {
            static_cast<replacement_policy::WeightedLRU*>(
                m_replacementPolicy_ptr)->touch(
                entry->replacementData, occupancy);
        } else {
            m_replacementPolicy_ptr->touch(entry->replacementData);
        }
        entry->setLastAccess(curTick());
    }
}

int
CacheMemory::getReplacementWeight(int64_t set, int64_t loc)
{
    assert(set < m_cache_num_sets);
    assert(loc < m_cache_assoc);
    int ret = 0;
    if (m_cache[set][loc] != NULL) {
        ret = m_cache[set][loc]->getNumValidBlocks();
        assert(ret >= 0);
    }

    return ret;
}

void
CacheMemory::recordCacheContents(int cntrl, CacheRecorder* tr) const
{
    uint64_t warmedUpBlocks = 0;
    [[maybe_unused]] uint64_t totalBlocks = (uint64_t)m_cache_num_sets *
                                         (uint64_t)m_cache_assoc;

    for (int i = 0; i < m_cache_num_sets; i++) {
        for (int j = 0; j < m_cache_assoc; j++) {
            if (m_cache[i][j] != NULL) {
                AccessPermission perm = m_cache[i][j]->m_Permission;
                RubyRequestType request_type = RubyRequestType_NULL;
                if (perm == AccessPermission_Read_Only) {
                    if (m_is_instruction_only_cache) {
                        request_type = RubyRequestType_IFETCH;
                    } else {
                        request_type = RubyRequestType_LD;
                    }
                } else if (perm == AccessPermission_Read_Write) {
                    request_type = RubyRequestType_ST;
                }

                if (request_type != RubyRequestType_NULL) {
                    Tick lastAccessTick;
                    lastAccessTick = m_cache[i][j]->getLastAccess();
                    tr->addRecord(cntrl, m_cache[i][j]->m_Address,
                                  0, request_type, lastAccessTick,
                                  m_cache[i][j]->getDataBlk());
                    warmedUpBlocks++;
                }
            }
        }
    }

    DPRINTF(RubyCacheTrace, "%s: %lli blocks of %lli total blocks"
            "recorded %.2f%% \n", name().c_str(), warmedUpBlocks,
            totalBlocks, (float(warmedUpBlocks) / float(totalBlocks)) * 100.0);
}

void
CacheMemory::print(std::ostream& out) const
{
    out << "Cache dump: " << name() << std::endl;
    for (int i = 0; i < m_cache_num_sets; i++) {
        for (int j = 0; j < m_cache_assoc; j++) {
            if (m_cache[i][j] != NULL) {
                out << "  Index: " << i
                    << " way: " << j
                    << " entry: " << *m_cache[i][j] << std::endl;
            } else {
                out << "  Index: " << i
                    << " way: " << j
                    << " entry: NULL" << std::endl;
            }
        }
    }
}

void
CacheMemory::printData(std::ostream& out) const
{
    out << "printData() not supported" << std::endl;
}

void
CacheMemory::setLocked(Addr address, int context)
{
    DPRINTF(RubyCache, "Setting Lock for addr: %#x to %d\n", address, context);
    AbstractCacheEntry* entry = lookup(address);
    assert(entry != nullptr);
    entry->setLocked(context);
}

void
CacheMemory::clearLocked(Addr address)
{
    DPRINTF(RubyCache, "Clear Lock for addr: %#x\n", address);
    AbstractCacheEntry* entry = lookup(address);
    assert(entry != nullptr);
    entry->clearLocked();
}

void
CacheMemory::clearLockedAll(int context)
{
    // iterate through every set and way to get a cache line
    for (auto i = m_cache.begin(); i != m_cache.end(); ++i) {
        std::vector<AbstractCacheEntry*> set = *i;
        for (auto j = set.begin(); j != set.end(); ++j) {
            AbstractCacheEntry *line = *j;
            if (line && line->isLocked(context)) {
                DPRINTF(RubyCache, "Clear Lock for addr: %#x\n",
                    line->m_Address);
                line->clearLocked();
            }
        }
    }
}

bool
CacheMemory::isLocked(Addr address, int context)
{
    AbstractCacheEntry* entry = lookup(address);
    assert(entry != nullptr);
    DPRINTF(RubyCache, "Testing Lock for addr: %#llx cur %d con %d\n",
            address, entry->m_locked, context);
    return entry->isLocked(context);
}

CacheMemory::
CacheMemoryStats::CacheMemoryStats(statistics::Group *parent,
                                 int topNSetCount,
                                 uint64_t maxReReferenceCycles)
    : statistics::Group(parent),
      ADD_STAT(numDataArrayReads, "Number of data array reads"),
      ADD_STAT(numDataArrayWrites, "Number of data array writes"),
      ADD_STAT(numTagArrayReads, "Number of tag array reads"),
      ADD_STAT(numTagArrayWrites, "Number of tag array writes"),
      ADD_STAT(numTagArrayStalls, "Number of stalls caused by tag array"),
      ADD_STAT(numDataArrayStalls, "Number of stalls caused by data array"),
      ADD_STAT(numAtomicALUOperations, "Number of atomic ALU operations"),
      ADD_STAT(numAtomicALUArrayStalls, "Number of stalls caused by atomic ALU array"),
      ADD_STAT(htmTransCommitReadSet, "Read set size of a committed "
                                      "transaction"),
      ADD_STAT(htmTransCommitWriteSet, "Write set size of a committed "
                                       "transaction"),
      ADD_STAT(htmTransAbortReadSet, "Read set size of a aborted transaction"),
      ADD_STAT(htmTransAbortWriteSet, "Write set size of a aborted "
                                      "transaction"),
      ADD_STAT(m_demand_hits, "Number of cache demand hits"),
      ADD_STAT(m_demand_misses, "Number of cache demand misses"),
      ADD_STAT(m_demand_accesses, "Number of cache demand accesses",
               m_demand_hits + m_demand_misses),
      ADD_STAT(m_prefetch_hits, "Number of cache prefetch hits"),
      ADD_STAT(m_prefetch_misses, "Number of cache prefetch misses"),
      /////////////////PRANJAL
      ADD_STAT(m_demand_hits_T1_T2,"Number of demand hits between T1 and T2"),
      ADD_STAT(m_demand_misses_T1_T2,"Number of demand miss between T1 and T2"),
      ADD_STAT(numEvictions, "Number of cache evictions"),
      ADD_STAT(topNSetIds, "Top N accessed cache set IDs"),
      ADD_STAT(topNSetCounts, "Top N accessed cache set counts"),
      ADD_STAT(hits_per_set, "Number of hits per cache set"),
      ADD_STAT(misses_per_set, "Number of misses per cache set"),
      ADD_STAT(hits_per_way, "Number of hits per cache way"),
      ADD_STAT(misses_per_way, "Number of misses per cache way"),
      // --- PAPER IMPLEMENTATION: Add Re-reference Stat ---
      ADD_STAT(m_re_reference_cycles, "Cycles between block eviction and re-reference"),
      ADD_STAT(m_total_re_reference_cycles, "Total sum of all re-reference cycles"),
      ADD_STAT(m_total_re_references, "Total count of successfully tracked re-references"),
      ADD_STAT(m_re_reference_histogram_overflows,
               "Re-reference intervals above the histogram bound (included in the mean)"),
      ADD_STAT(m_tracked_re_reference_addresses,
               "Addresses retained for continued re-reference tracking"),
      ADD_STAT(m_avg_re_reference_cycles, "Running average of cycles between block eviction and re-reference"),
      ADD_STAT(m_llc_miss_cycles, "L2 off-chip miss completion latency in Ruby cycles"),
      ADD_STAT(m_llc_miss_memory_cycles, "L2 miss latency for memory replies"),
      ADD_STAT(m_llc_miss_dirty_local_cycles, "L2 miss latency for dirty SRFD replies"),
      ADD_STAT(m_llc_miss_clean_local_cycles, "L2 miss latency for clean SRFD replies"),
      ADD_STAT(m_llc_miss_total_cycles, "Total L2 off-chip miss completion cycles"),
      ADD_STAT(m_llc_miss_count, "Count of completed L2 off-chip misses"),
      ADD_STAT(m_llc_miss_memory_total_cycles, "Total cycles for memory L2 miss replies"),
      ADD_STAT(m_llc_miss_memory_count, "Count of memory L2 miss replies"),
      ADD_STAT(m_llc_miss_dirty_local_total_cycles, "Total cycles for dirty SRFD replies"),
      ADD_STAT(m_llc_miss_dirty_local_count, "Count of dirty SRFD replies"),
      ADD_STAT(m_llc_miss_clean_local_total_cycles, "Total cycles for clean SRFD replies"),
      ADD_STAT(m_llc_miss_clean_local_count, "Count of clean SRFD replies"),
      ADD_STAT(m_llc_miss_untracked_completions, "L2 completions whose start preceded a stats reset"),
      ADD_STAT(m_srfd_clean_candidates, "Acknowledged clean-exclusive eviction candidates"),
      ADD_STAT(m_srfd_clean_emitted, "Clean PUTE-equivalent SRFD packets emitted"),
      ADD_STAT(m_srfd_l1_clean_exclusive_installs, "Clean-exclusive lines installed in this L1"),
      ADD_STAT(m_srfd_l1_clean_replacements, "Clean-exclusive L1 replacement candidates"),
      ADD_STAT(m_srfd_l1_clean_writebacks, "WRITEBACK_CLEAN_DATA messages emitted by this L1"),
      ADD_STAT(m_srfd_can_put_dirty_sent, "Dirty SRFD CAN_PUT messages sent"),
      ADD_STAT(m_srfd_can_put_clean_sent, "Clean SRFD CAN_PUT messages sent"),
      // ---------------------------------------------------
      /////////////////PRANJAL
      ADD_STAT(m_prefetch_accesses, "Number of cache prefetch accesses",
               m_prefetch_hits + m_prefetch_misses),
      ADD_STAT(m_accessModeType, "")
{
    const int validTopNSize = std::max(1, topNSetCount);
    topNSetIds.init(validTopNSize);
    topNSetCounts.init(validTopNSize);

    numDataArrayReads
        .flags(statistics::nozero);

    numDataArrayWrites
        .flags(statistics::nozero);

    numTagArrayReads
        .flags(statistics::nozero);

    numTagArrayWrites
        .flags(statistics::nozero);

    numTagArrayStalls
        .flags(statistics::nozero);

    numDataArrayStalls
        .flags(statistics::nozero);

    numAtomicALUOperations
        .flags(statistics::nozero);

    numAtomicALUArrayStalls
        .flags(statistics::nozero);

    htmTransCommitReadSet
        .init(8)
        .flags(statistics::pdf | statistics::dist | statistics::nozero |
            statistics::nonan);

    htmTransCommitWriteSet
        .init(8)
        .flags(statistics::pdf | statistics::dist | statistics::nozero |
            statistics::nonan);

    htmTransAbortReadSet
        .init(8)
        .flags(statistics::pdf | statistics::dist | statistics::nozero |
            statistics::nonan);

    htmTransAbortWriteSet
        .init(8)
        .flags(statistics::pdf | statistics::dist | statistics::nozero |
            statistics::nonan);

    m_prefetch_hits
        .flags(statistics::nozero);

    m_prefetch_misses
        .flags(statistics::nozero);

    m_prefetch_accesses
        .flags(statistics::nozero);

    m_accessModeType
        .init(RubyRequestType_NUM)
        .flags(statistics::pdf | statistics::total);

    // --- PAPER IMPLEMENTATION: Configure Histogram ---
    m_re_reference_cycles
        .init(1, maxReReferenceCycles, 5000)
        .flags(statistics::pdf | statistics::dist | statistics::nozero | statistics::nonan);
    m_total_re_reference_cycles.flags(statistics::nozero);
    m_total_re_references.flags(statistics::nozero);
    m_re_reference_histogram_overflows.flags(statistics::nozero);
    m_tracked_re_reference_addresses.flags(statistics::nozero);
    
    // Calculate the running average dynamically
    m_avg_re_reference_cycles = m_total_re_reference_cycles / m_total_re_references;
    m_avg_re_reference_cycles.flags(statistics::nozero);
    auto initLlcLatency = [](statistics::Distribution &dist) {
        dist.init(1, 100000, 1000)
            .flags(statistics::pdf | statistics::dist |
                   statistics::nozero | statistics::nonan);
    };
    initLlcLatency(m_llc_miss_cycles);
    initLlcLatency(m_llc_miss_memory_cycles);
    initLlcLatency(m_llc_miss_dirty_local_cycles);
    initLlcLatency(m_llc_miss_clean_local_cycles);
    // -------------------------------------------------

    for (int i = 0; i < RubyAccessMode_NUM; i++) {
        m_accessModeType
            .subname(i, RubyAccessMode_to_string(RubyAccessMode(i)))
            .flags(statistics::nozero)
            ;
    }
}

// assumption: SLICC generated files will only call this function
// once **all** resources are granted
void
CacheMemory::recordRequestType(CacheRequestType requestType, Addr addr)
{
    DPRINTF(RubyStats, "Recorded statistic: %s\n",
            CacheRequestType_to_string(requestType));
    //PRANJAL
    if (m_top_n_set > 0 && !m_set_access_counts.empty()) {
        int64_t set = addressToCacheSet(addr);
        if (set >= 0 && set < static_cast<int64_t>(m_set_access_counts.size())) {
            m_set_access_counts[set]++;
            updateTopNSetAccesses();
        }
    }
    //PRANJAL

    switch(requestType) {
    case CacheRequestType_DataArrayRead:
        if (m_resource_stalls)
            dataArray.reserve(addressToCacheSet(addr));
        cacheMemoryStats.numDataArrayReads++;
        return;
    case CacheRequestType_DataArrayWrite:
        if (m_resource_stalls)
            dataArray.reserve(addressToCacheSet(addr));
        cacheMemoryStats.numDataArrayWrites++;
        return;
    case CacheRequestType_TagArrayRead:
        if (m_resource_stalls)
            tagArray.reserve(addressToCacheSet(addr));
        cacheMemoryStats.numTagArrayReads++;
        return;
    case CacheRequestType_TagArrayWrite:
        if (m_resource_stalls)
            tagArray.reserve(addressToCacheSet(addr));
        cacheMemoryStats.numTagArrayWrites++;
        return;
    case CacheRequestType_AtomicALUOperation:
        if (m_resource_stalls)
            atomicALUArray.reserve(addr);
        cacheMemoryStats.numAtomicALUOperations++;
        return;
    default:
        warn("CacheMemory access_type not found: %s",
             CacheRequestType_to_string(requestType));
    }
}

bool
CacheMemory::checkResourceAvailable(CacheResourceType res, Addr addr)
{
    if (!m_resource_stalls) {
        return true;
    }

    if (res == CacheResourceType_TagArray) {
        if (tagArray.tryAccess(addressToCacheSet(addr))) return true;
        else {
            DPRINTF(RubyResourceStalls,
                    "Tag array stall on addr %#x in set %d\n",
                    addr, addressToCacheSet(addr));
            cacheMemoryStats.numTagArrayStalls++;
            return false;
        }
    } else if (res == CacheResourceType_DataArray) {
        if (dataArray.tryAccess(addressToCacheSet(addr))) return true;
        else {
            DPRINTF(RubyResourceStalls,
                    "Data array stall on addr %#x in set %d\n",
                    addr, addressToCacheSet(addr));
            cacheMemoryStats.numDataArrayStalls++;
            return false;
        }
    } else if (res == CacheResourceType_AtomicALUArray) {
        if (atomicALUArray.tryAccess(addr)) return true;
        else {
            DPRINTF(RubyResourceStalls,
                    "Atomic ALU array stall on addr %#x in line address %#x\n",
                    addr, makeLineAddress(addr));
            cacheMemoryStats.numAtomicALUArrayStalls++;
            return false;
        }
    } else {
        panic("Unrecognized cache resource type.");
    }
}

bool
CacheMemory::isBlockInvalid(int64_t cache_set, int64_t loc)
{
  return (m_cache[cache_set][loc]->m_Permission == AccessPermission_Invalid);
}

bool
CacheMemory::isBlockNotBusy(int64_t cache_set, int64_t loc)
{
  return (m_cache[cache_set][loc]->m_Permission != AccessPermission_Busy);
}

/* hardware transactional memory */

void
CacheMemory::htmAbortTransaction()
{
    uint64_t htmReadSetSize = 0;
    uint64_t htmWriteSetSize = 0;

    // iterate through every set and way to get a cache line
    for (auto i = m_cache.begin(); i != m_cache.end(); ++i)
    {
        std::vector<AbstractCacheEntry*> set = *i;

        for (auto j = set.begin(); j != set.end(); ++j)
        {
            AbstractCacheEntry *line = *j;

            if (line != nullptr) {
                htmReadSetSize += (line->getInHtmReadSet() ? 1 : 0);
                htmWriteSetSize += (line->getInHtmWriteSet() ? 1 : 0);
                if (line->getInHtmWriteSet()) {
                    line->invalidateEntry();
                }
                line->setInHtmWriteSet(false);
                line->setInHtmReadSet(false);
                line->clearLocked();
            }
        }
    }

    cacheMemoryStats.htmTransAbortReadSet.sample(htmReadSetSize);
    cacheMemoryStats.htmTransAbortWriteSet.sample(htmWriteSetSize);
    DPRINTF(HtmMem, "htmAbortTransaction: read set=%u write set=%u\n",
        htmReadSetSize, htmWriteSetSize);
}

void
CacheMemory::htmCommitTransaction()
{
    uint64_t htmReadSetSize = 0;
    uint64_t htmWriteSetSize = 0;

    // iterate through every set and way to get a cache line
    for (auto i = m_cache.begin(); i != m_cache.end(); ++i)
    {
        std::vector<AbstractCacheEntry*> set = *i;

        for (auto j = set.begin(); j != set.end(); ++j)
        {
            AbstractCacheEntry *line = *j;
            if (line != nullptr) {
                htmReadSetSize += (line->getInHtmReadSet() ? 1 : 0);
                htmWriteSetSize += (line->getInHtmWriteSet() ? 1 : 0);
                line->setInHtmWriteSet(false);
                line->setInHtmReadSet(false);
                line->clearLocked();
             }
        }
    }

    cacheMemoryStats.htmTransCommitReadSet.sample(htmReadSetSize);
    cacheMemoryStats.htmTransCommitWriteSet.sample(htmWriteSetSize);
    DPRINTF(HtmMem, "htmCommitTransaction: read set=%u write set=%u\n",
        htmReadSetSize, htmWriteSetSize);
}

// void
// CacheMemory::profileDemandHit()
// {
//     cacheMemoryStats.m_demand_hits++;
// }

// void
// CacheMemory::profileDemandMiss()
// {
//     cacheMemoryStats.m_demand_misses++;
// }
////////////////////////////////////////////////PRANJAL
void
 CacheMemory::profileDemandHit()
 {
     const Tick T1 = 1500000000;                     // CHANGES START FOR PART A OF E2.
     const Tick T2 = 1625000000;
     cacheMemoryStats.m_demand_hits++;
     if(curTick()>T1 && curTick()<T2){
       cacheMemoryStats.m_demand_hits_T1_T2++;            // IF THE curTick() value is between 5000000 and 6000000 then increment value of demand hits
     }
 }
 
 void
 CacheMemory::profileDemandMiss()
 {
     const Tick T1 = 1500000000;
     const Tick T2 = 1625000000;
     cacheMemoryStats.m_demand_misses++;
     if(curTick()>T1 && curTick()<T2){
       cacheMemoryStats.m_demand_misses_T1_T2++;           // IF THE curTick() value is between 5000000 and 6000000 then increment value of demand MISSES
     }
 }
////////////////////////////////////////////////PRANJAL

void
CacheMemory::profilePrefetchHit()
{
    cacheMemoryStats.m_prefetch_hits++;
}

void
CacheMemory::profilePrefetchMiss()
{
    cacheMemoryStats.m_prefetch_misses++;
}

} // namespace ruby
} // namespace gem5
