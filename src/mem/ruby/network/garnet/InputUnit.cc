/*
 * Copyright (c) 2020 Inria
 * Copyright (c) 2016 Georgia Institute of Technology
 * Copyright (c) 2008 Princeton University
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


#include "mem/ruby/network/garnet/InputUnit.hh"

#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/Credit.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/protocol/MachineType.hh"
#include "mem/ruby/system/RubySystem.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

InputUnit::InputUnit(int id, PortDirection direction, Router *router)
  : Consumer(router), m_router(router), m_id(id), m_direction(direction),
    m_vc_per_vnet(m_router->get_vc_per_vnet())
{
    const int m_num_vcs = m_router->get_num_vcs();
    m_num_buffer_reads.resize(m_num_vcs/m_vc_per_vnet);
    m_num_buffer_writes.resize(m_num_vcs/m_vc_per_vnet);
    for (int i = 0; i < m_num_buffer_reads.size(); i++) {
        m_num_buffer_reads[i] = 0;
        m_num_buffer_writes[i] = 0;
    }

    // Instantiating the virtual channels
    virtualChannels.reserve(m_num_vcs);
    for (int i=0; i < m_num_vcs; i++) {
        virtualChannels.emplace_back();
    }
    m_srfd.resize(m_num_vcs);
    m_srfd_waiting.resize(m_num_vcs, false);
    m_srfd_clean_bypass.resize(m_num_vcs, false);

    //PRANJAL
    // --- PAPER IMPLEMENTATION: Initialize VC Tracking ---
    m_free_vcs = m_num_vcs;
    m_last_vc_update_cycle = 0;
    statistics::registerDumpCallback(
        [this]() {
            update_vc_availability();
            update_srfd_occupancy();
            // Legacy stats are reset after SimObject::resetStats callbacks.
            // Keep the opening snapshot in runtime state until the dump.
            m_srfd_opening_resident = m_srfd_opening_count;
            m_srfd_resident = m_srfd_stored_count;
            m_srfd_max_stored = std::max(m_srfd_max_stored.value(),
                static_cast<double>(m_srfd_opening_count));
        });
}

/*
 * The InputUnit wakeup function reads the input flit from its input link.
 * Each flit arrives with an input VC.
 * For HEAD/HEAD_TAIL flits, performs route computation,
 * and updates route in the input VC.
 * The flit is buffered for (m_latency - 1) cycles in the input VC
 * and marked as valid for SwitchAllocation starting that cycle.
 *
 */

void
InputUnit::wakeup()
{
    flit *t_flit;
    if (m_in_link->isReady(curTick())) {

        t_flit = m_in_link->consumeLink();
        DPRINTF(RubyNetwork, "Router[%d] Consuming:%s Width: %d Flit:%s\n",
        m_router->get_id(), m_in_link->name(),
        m_router->getBitWidth(), *t_flit);
        assert(t_flit->m_width == m_router->getBitWidth());
        int vc = t_flit->get_vc();
        t_flit->increment_hops(); // for stats

        SrfdRequestResult srfd_result = SrfdRequestResult::Miss;
        if (m_router->srfdEnabled() && isLocalPacket() &&
            t_flit->get_type() == HEAD_TAIL_ &&
            (t_flit->get_msg_ptr()->getSRFDGetS() ||
             t_flit->get_msg_ptr()->getSRFDGetX())) {
            srfd_result = trySrfdRequest(t_flit);
            if (srfd_result == SrfdRequestResult::Hit) {
                returnDroppedRequestCredit(vc);
                delete t_flit;
                if (m_in_link->isReady(curTick()))
                    m_router->schedule_wakeup(Cycles(1));
                return;
            }
        }

        if ((t_flit->get_type() == HEAD_) ||
            (t_flit->get_type() == HEAD_TAIL_)) {
            
            assert(virtualChannels[vc].get_state() == IDLE_);
            set_vc_active(vc, curTick());
            //PRANJAL
            // --- PAPER IMPLEMENTATION: VC Allocated ---
            update_vc_availability();
            m_free_vcs--;
            m_srfd_waiting[vc] = srfd_result == SrfdRequestResult::Wait;
            // ------------------------------------------

            const MsgPtr &msg = t_flit->get_msg_ptr();
            const bool store = m_router->srfdEnabled() && isLocalPacket() &&
                !m_router->srfdDisabledAtThisRouter() && msg->getSRFDStore() &&
                (msg->getSRFDDirty() || m_router->srfdStoresClean());
            if (store) {
                if (msg->getSRFDDirty()) ++m_srfd_dirty_offered;
                else ++m_srfd_clean_offered;
                fatal_if(t_flit->get_size() >
                         m_router->get_net_ptr()->getBuffersPerDataVC(),
                         "SRFD packet does not fit in one data VC");
                for (int other = 0; other < m_srfd.size(); ++other) {
                    if (!m_srfd[other].held ||
                        m_srfd[other].address != msg->getaddr()) {
                        continue;
                    }

                    // A buffered clean copy is invisible to the directory.
                    // The same block can consequently be fetched, cleanly
                    // evicted, and offered again before the first copy leaves
                    // this router.  Coalesce deterministically by discarding
                    // the older redundant clean copy.  Dirty duplicates would
                    // imply two authoritative copies and remain a protocol
                    // error.
                    fatal_if(m_srfd[other].dirty,
                             "duplicate dirty SRFD block %#x at router %d",
                             msg->getaddr(), m_router->get_id());
                    fatal_if(!m_srfd[other].complete,
                             "overlapping incomplete SRFD block %#x at router %d",
                             msg->getaddr(), m_router->get_id());
                    releaseSrfd(other, true);
                }
                if (m_srfd_stored_count >= m_router->srfdStorageCapacity()) {
                    // Count incomplete retained packets against the limit as
                    // well. Interleaved headers must not consume the headroom.
                    // Dirty overflow takes its ordinary writeback route;
                    // clean overflow is dropped only after its tail arrives.
                    if (msg->getSRFDDirty()) {
                        ++m_srfd_dirty_bypassed;
                    } else {
                        ++m_srfd_clean_bypassed;
                        m_srfd_clean_bypass[vc] = true;
                    }
                } else {
                    auto &entry = m_srfd[vc];
                    entry.held = true;
                    entry.complete = t_flit->get_type() == HEAD_TAIL_;
                    entry.dirty = msg->getSRFDDirty();
                    entry.address = msg->getaddr();
                    entry.sequence = ++m_srfd_sequence;
                    entry.stored_tick = curTick();
                    update_srfd_occupancy();
                    ++m_srfd_stored_count;
                    m_srfd_resident = m_srfd_stored_count;
                    if (entry.dirty) ++m_srfd_dirty_stored;
                    else ++m_srfd_clean_stored;
                    if (m_srfd_stored_count > m_srfd_max_stored.value())
                        m_srfd_max_stored = m_srfd_stored_count;
                    assert(m_srfd_stored_count <=
                           m_router->srfdStorageCapacity());
                }
            }
            //PRANJAL
            m_local_packets_generated += isLocalPacket();
            m_router->get_net_ptr()->recordPacketRouter(
                t_flit->getPacketID(),
                m_router->get_id());

            // Route computation for this vc
            int outport = m_router->route_compute(t_flit->get_route(),
                m_id, m_direction);

            // Update output port in VC
            // All flits in this packet will use this output port
            // The output port field in the flit is updated after it wins SA
            grant_outport(vc, outport);

        } else {
            assert(virtualChannels[vc].get_state() == ACTIVE_);
        }


        // Buffer the flit
        virtualChannels[vc].insertFlit(t_flit);
        if (m_srfd[vc].held &&
            (t_flit->get_type() == TAIL_ ||
             t_flit->get_type() == HEAD_TAIL_)) {
            m_srfd[vc].complete = true;
        }


        int vnet = vc/m_vc_per_vnet;
        // number of writes same as reads
        // any flit that is written will be read only once
        m_num_buffer_writes[vnet]++;
        m_num_buffer_reads[vnet]++;

        if (!m_srfd_waiting[vc]) {
            Cycles pipe_stages = m_router->get_pipe_stages();
            if (pipe_stages == 1) {
                // 1-cycle router
                // Flit goes for SA directly
                t_flit->advance_stage(SA_, curTick());
            } else {
                assert(pipe_stages > 1);
                // Router delay is modeled by making flit wait in buffer for
                // (pipe_stages cycles - 1) cycles before going for SA

                Cycles wait_time = pipe_stages - Cycles(1);
                t_flit->advance_stage(SA_, m_router->clockEdge(wait_time));

                // Wakeup the router in that cycle to perform SA
                m_router->schedule_wakeup(Cycles(wait_time));
            }
        }

        // Retrying a waiting GETX against a newly completed clean packet can
        // drop the stored packet.  releaseSrfd() then removes and deletes all
        // of its flits, including t_flit when this arrival is the tail.  Keep
        // this callback after the last use of t_flit in wakeup() to avoid a
        // use-after-free on the advance_stage() path above.
        if (m_router->srfdEnabled() && isLocalPacket() &&
            t_flit->get_msg_ptr()->getSRFDStore() &&
            (t_flit->get_type() == TAIL_ ||
             t_flit->get_type() == HEAD_TAIL_)) {
            const Addr address = t_flit->get_msg_ptr()->getaddr();
            if (m_srfd_clean_bypass[vc])
                discardCleanPacket(vc);
            m_router->get_net_ptr()->getRubySystem()->completeSrfdStore(address);
            retryWaitingSrfdRequests(address);
        }

        if (m_in_link->isReady(curTick())) {
            m_router->schedule_wakeup(Cycles(1));
        }
    }
}

// Send a credit back to upstream router for this VC.
// Called by SwitchAllocator when the flit in this VC wins the Switch.
void
InputUnit::increment_credit(int in_vc, bool free_signal, Tick curTime)
{
    DPRINTF(RubyNetwork, "Router[%d]: Sending a credit vc:%d free:%d to %s\n",
    m_router->get_id(), in_vc, free_signal, m_credit_link->name());
    // --- PAPER IMPLEMENTATION: VC Freed PRANJAL---
    if (free_signal) {
        update_vc_availability();
        m_free_vcs++;
        assert(m_free_vcs <= m_router->get_num_vcs());
    }
    // --------------------------------------
    Credit *t_credit = new Credit(in_vc, free_signal, curTime);
    creditQueue.insert(t_credit);
    m_credit_link->scheduleEventAbsolute(m_router->clockEdge(Cycles(1)));
}

int
InputUnit::oldestStored(int vnet, bool complete_only) const
{
    int result = -1;
    uint64_t oldest = std::numeric_limits<uint64_t>::max();
    const int begin = vnet * m_vc_per_vnet;
    const int end = begin + m_vc_per_vnet;
    for (int vc = begin; vc < end; ++vc) {
        const auto &entry = m_srfd[vc];
        if (entry.held && (!complete_only || entry.complete) &&
            entry.sequence < oldest) {
            result = vc;
            oldest = entry.sequence;
        }
    }
    return result;
}

void
InputUnit::returnDroppedRequestCredit(int vc)
{
    Credit *credit = new Credit(vc, true, curTick());
    creditQueue.insert(credit);
    m_credit_link->scheduleEventAbsolute(m_router->clockEdge(Cycles(1)));
}

void
InputUnit::discardCleanPacket(int vc)
{
    while (virtualChannels[vc].isReady(curTick())) {
        flit *victim = virtualChannels[vc].getTopFlit();
        const bool tail = victim->get_type() == TAIL_ ||
                          victim->get_type() == HEAD_TAIL_;
        delete victim;
        increment_credit(vc, tail, curTick());
    }
    set_vc_idle(vc, curTick());
    m_srfd_clean_bypass[vc] = false;
}

void
InputUnit::releaseSrfd(int vc, bool drop)
{
    auto &entry = m_srfd[vc];
    assert(entry.held && entry.complete);
    m_srfd_residence_cycles.sample(
        (curTick() - entry.stored_tick) / m_router->clockPeriod());
    if (drop) {
        discardCleanPacket(vc);
        ++m_srfd_clean_dropped;
    } else {
        virtualChannels[vc].peekTopFlit()->advance_stage(SA_, curTick());
        ++m_srfd_dirty_forwarded;
        m_router->schedule_wakeup(Cycles(1));
    }
    entry = SrfdEntry();
    assert(m_srfd_stored_count > 0);
    update_srfd_occupancy();
    --m_srfd_stored_count;
    m_srfd_resident = m_srfd_stored_count;
}

bool
InputUnit::applySrfdPressure(int vnet)
{
    panic_if(vnet < 0 || vnet >= m_router->get_num_vnets(),
             "Invalid SRFD pressure vnet %d at router %d input %d", vnet,
             m_router->get_id(), m_id);
    ++m_srfd_pressure_attempts;
    const int begin = vnet * m_vc_per_vnet;
    const int end = begin + m_vc_per_vnet;
    int stored = 0;
    for (int vc = begin; vc < end; ++vc) {
        stored += m_srfd[vc].held && m_srfd[vc].complete;
    }
    const unsigned capacity = m_router->srfdStorageCapacity();
    const bool pressure = m_router->srfdDefensive() ?
        (stored > 0) : (capacity > 0 && stored >= capacity);
    if (!pressure) {
        ++m_srfd_pressure_no_victim;
        return false;
    }
    const int victim = oldestStored(vnet);
    if (victim >= 0) {
        ++m_srfd_pressure_events;
        releaseSrfd(victim, !m_srfd[victim].dirty);
    }
    if (victim < 0) ++m_srfd_pressure_no_victim;
    return victim >= 0;
}

InputUnit::SrfdRequestResult
InputUnit::trySrfdRequest(flit *request, bool count_lookup)
{
    const MsgPtr &request_msg = request->get_msg_ptr();
    const bool getx = request_msg->getSRFDGetX();
    if (count_lookup) {
        if (getx) ++m_srfd_getx_lookups; else ++m_srfd_gets_lookups;
    }
    if (m_router->get_net_ptr()->getRubySystem()->
        srfdStorePending(request_msg->getaddr())) {
        if (count_lookup) ++m_srfd_incomplete_misses;
        return SrfdRequestResult::Wait;
    }
    int match = -1;
    uint64_t oldest = std::numeric_limits<uint64_t>::max();
    bool incomplete = false;
    for (int vc = 0; vc < m_srfd.size(); ++vc) {
        const auto &entry = m_srfd[vc];
        if (!entry.held || entry.address != request_msg->getaddr()) continue;
        incomplete |= !entry.complete;
        if (entry.complete && entry.sequence < oldest) {
            match = vc;
            oldest = entry.sequence;
        }
    }
    if (match < 0) {
        if (incomplete) {
            ++m_srfd_incomplete_misses;
            return SrfdRequestResult::Wait;
        }
        return SrfdRequestResult::Miss;
    }
    if (getx && !m_srfd[match].dirty) {
        ++m_srfd_getx_clean_conflicts;
        releaseSrfd(match, true);
        return SrfdRequestResult::Miss;
    }

    flit *reply = virtualChannels[match].peekTopFlit();
    RouteInfo route = reply->get_route();
    route.dest_ni = route.src_ni;
    route.dest_router = route.src_router;
    route.src_router = m_router->get_id();
    route.hops_traversed = -1;
    NetDest destination(m_router->get_net_ptr()->getRubySystem());
    for (int type = 0; type < static_cast<int>(MachineType_NUM); ++type) {
        const auto machine_type = static_cast<MachineType>(type);
        const int base = m_router->get_net_ptr()->getRubySystem()->
            MachineType_base_number(machine_type);
        const int next = m_router->get_net_ptr()->getRubySystem()->
            MachineType_base_number(
            static_cast<MachineType>(type + 1));
        if (route.dest_ni >= base && route.dest_ni < next) {
            MachineID id{machine_type,
                static_cast<NodeID>(route.dest_ni - base)};
            destination.add(id);
            break;
        }
    }
    fatal_if(destination.isEmpty(), "Unable to construct SRFD reply route");
    route.net_dest = destination;
    reply->set_route(route);
    reply->get_msg_ptr()->getDestination().clear();
    reply->get_msg_ptr()->getDestination().addNetDest(destination);
    reply->get_msg_ptr()->setSRFDReply(true);
    grant_outport(match, m_router->route_compute(route, m_id, m_direction));
    m_srfd_residence_cycles.sample(
        (curTick() - m_srfd[match].stored_tick) / m_router->clockPeriod());
    m_router->get_net_ptr()->getRubySystem()->recordSrfdReply(m_srfd[match].dirty);
    if (m_srfd[match].dirty) {
        ++m_srfd_dirty_hits;
        if (getx) ++m_srfd_dirty_getx_hits;
        else ++m_srfd_dirty_gets_hits;
    } else {
        ++m_srfd_clean_hits;
        ++m_srfd_clean_gets_hits;
    }
    ++m_srfd_avoided_requests;
    m_srfd[match] = SrfdEntry();
    update_srfd_occupancy();
    --m_srfd_stored_count;
    m_srfd_resident = m_srfd_stored_count;
    const Cycles delay = m_router->get_pipe_stages() - Cycles(1);
    reply->advance_stage(SA_, m_router->clockEdge(delay));
    m_router->schedule_wakeup(delay == Cycles(0) ? Cycles(1) : delay);
    return SrfdRequestResult::Hit;
}

void
InputUnit::retryWaitingSrfdRequests(Addr address)
{
    for (int vc = 0; vc < m_srfd_waiting.size(); ++vc) {
        if (!m_srfd_waiting[vc]) continue;
        flit *request = virtualChannels[vc].peekTopFlit();
        if (request->get_msg_ptr()->getaddr() != address) continue;

        const auto result = trySrfdRequest(request, false);
        assert(result != SrfdRequestResult::Wait);
        m_srfd_waiting[vc] = false;
        if (result == SrfdRequestResult::Hit) {
            flit *removed = virtualChannels[vc].getTopFlit();
            assert(removed == request);
            increment_credit(vc, true, curTick());
            set_vc_idle(vc, curTick());
            delete request;
        } else {
            const Cycles delay = m_router->get_pipe_stages() - Cycles(1);
            request->advance_stage(SA_, m_router->clockEdge(delay));
            m_router->schedule_wakeup(delay == Cycles(0) ? Cycles(1) : delay);
        }
    }
}

bool
InputUnit::functionalRead(Packet *pkt, WriteMask &mask)
{
    bool read = false;
    for (auto& virtual_channel : virtualChannels) {
        if (virtual_channel.functionalRead(pkt, mask))
            read = true;
    }

    return read;
}

uint32_t
InputUnit::functionalWrite(Packet *pkt)
{
    uint32_t num_functional_writes = 0;
    for (auto& virtual_channel : virtualChannels) {
        num_functional_writes += virtual_channel.functionalWrite(pkt);
    }

    return num_functional_writes;
}

void
InputUnit::resetStats()
{
    for (int j = 0; j < m_num_buffer_reads.size(); j++) {
        m_num_buffer_reads[j] = 0;
        m_num_buffer_writes[j] = 0;
    }

    //PRANJAL
    m_local_packets_generated = 0;
    for (auto &entry : m_srfd)
        if (entry.held) entry.stored_tick = curTick();
    m_srfd_last_occupancy_cycle = (uint64_t)m_router->curCycle();
    m_srfd_resident = m_srfd_stored_count;
    m_srfd_opening_count = m_srfd_stored_count;
    for (int i = 0; i <= m_router->get_num_vcs(); ++i)
        m_srfd_occupancy_cycles[i] = 0;
    // --- PAPER IMPLEMENTATION: Drop Fast-Forward Cycles ---
    if (m_direction == "Local") {
        m_last_vc_update_cycle = (uint64_t)m_router->curCycle();
        for (int i = 0; i <= m_router->get_num_vcs(); i++) {
            vc_availability_stat[i] = 0;
        }
    }
}

//PRANJAL

void
InputUnit::regStats()
{
    // Name and initialize the stat for ALL directions so gem5 doesn't crash
    vc_availability_stat
        .init(m_router->get_num_vcs() + 1)
        .name(m_router->name() + ".vc_avail_" + m_direction + "_port" + std::to_string(m_id))
        .desc("Cycles where exactly n VCs are free (index = n)")
        .flags(gem5::statistics::pdf);

    const std::string prefix = m_router->name() + ".srfd_" +
        m_direction + "_port" + std::to_string(m_id) + ".";
    m_srfd_dirty_offered.name(prefix + "dirty_offered");
    m_srfd_clean_offered.name(prefix + "clean_offered");
    m_srfd_dirty_stored.name(prefix + "dirty_stored");
    m_srfd_clean_stored.name(prefix + "clean_stored");
    m_srfd_dirty_bypassed.name(prefix + "dirty_bypassed")
        .desc("Dirty candidates forwarded without storage at the capacity limit");
    m_srfd_clean_bypassed.name(prefix + "clean_bypassed")
        .desc("Clean candidates discarded without storage at the capacity limit");
    m_srfd_dirty_forwarded.name(prefix + "dirty_forwarded");
    m_srfd_clean_dropped.name(prefix + "clean_dropped");
    m_srfd_gets_lookups.name(prefix + "gets_lookups");
    m_srfd_getx_lookups.name(prefix + "getx_lookups");
    m_srfd_clean_hits.name(prefix + "clean_hits");
    m_srfd_dirty_hits.name(prefix + "dirty_hits");
    m_srfd_clean_gets_hits.name(prefix + "clean_gets_hits");
    m_srfd_dirty_gets_hits.name(prefix + "dirty_gets_hits");
    m_srfd_dirty_getx_hits.name(prefix + "dirty_getx_hits");
    m_srfd_getx_clean_conflicts.name(prefix + "getx_clean_conflicts");
    m_srfd_incomplete_misses.name(prefix + "incomplete_misses");
    m_srfd_pressure_events.name(prefix + "pressure_events");
    m_srfd_pressure_attempts.name(prefix + "pressure_attempts");
    m_srfd_pressure_no_victim.name(prefix + "pressure_no_victim");
    m_srfd_avoided_requests.name(prefix + "avoided_requests");
    m_srfd_max_stored.name(prefix + "max_stored");
    m_srfd_resident.name(prefix + "resident");
    m_srfd_opening_resident.name(prefix + "opening_resident");
    m_srfd_occupancy_cycles
        .init(m_router->get_num_vcs() + 1)
        .name(prefix + "occupancy_cycles")
        .desc("Cycles with exactly n SRFD packets resident")
        .flags(statistics::pdf);
    m_srfd_residence_cycles
        .init(0, 100000, 100)
        .name(prefix + "residence_cycles")
        .desc("SRFD storage residence time in router cycles");
}

void
InputUnit::update_srfd_occupancy()
{
    const uint64_t current_cycle = (uint64_t)m_router->curCycle();
    if (current_cycle > m_srfd_last_occupancy_cycle) {
        m_srfd_occupancy_cycles[m_srfd_stored_count] +=
            current_cycle - m_srfd_last_occupancy_cycle;
    }
    m_srfd_last_occupancy_cycle = current_cycle;
}

// --- PAPER IMPLEMENTATION: Update & Register Stats ---
void
InputUnit::update_vc_availability()
{
    if (m_direction == "Local") {
        uint64_t current_cycle = (uint64_t)m_router->curCycle();
        uint64_t delta = current_cycle - m_last_vc_update_cycle;
        if (delta > 0) {
            vc_availability_stat[m_free_vcs] += delta;
            m_last_vc_update_cycle = current_cycle;
        }
    }
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
