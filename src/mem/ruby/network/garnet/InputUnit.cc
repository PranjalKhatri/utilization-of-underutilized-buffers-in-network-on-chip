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
#include "mem/ruby/network/garnet/OutputUnit.hh"
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
    m_srfd_leases.resize(m_num_vcs, 0);
    m_srfd_reclaim_waiting.resize(m_router->get_num_vnets(), false);
    m_srfd_reclaim_start.resize(m_router->get_num_vnets(), 0);
    m_srfd_reclaim_epoch.resize(m_router->get_num_vnets(), 0);
    m_srfd_reclaim_victim.resize(m_router->get_num_vnets(), -1);

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
            m_srfd_opening_staged_offers = m_srfd_opening_staged_offers_count;
            m_srfd_opening_staged_clean = m_srfd_opening_staged_kind[0];
            m_srfd_opening_staged_dirty = m_srfd_opening_staged_kind[1];
            m_srfd_resident = m_srfd_stored_count;
            unsigned staged[2] = {};
            for (const auto &entry : m_srfd) {
                if (entry.admission_pending) ++staged[entry.dirty];
                if (entry.held && entry.staging && entry.previously_stored)
                    m_srfd_resident += 1;
            }
            m_srfd_closing_staged_clean = staged[0];
            m_srfd_closing_staged_dirty = staged[1];
            m_srfd_opening_leases = m_srfd_opening_leases_count;
            m_srfd_closing_leases = std::count_if(m_srfd_leases.begin(),
                m_srfd_leases.end(), [](uint64_t lease) { return lease != 0; });
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
        fatal_if(m_srfd_leases[vc],
                 "Link flit arrived in a locally leased SRFD VC %d", vc);
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
                if (m_router->directionalSrfd()) {
                    const auto old = m_router->findSrfd(msg->getaddr());
                    if (old.first) {
                        const auto &entry = old.first->m_srfd[old.second];
                        fatal_if(entry.dirty || !entry.complete || entry.staging,
                                 "Overlapping authoritative/incomplete SRFD copy %#x", msg->getaddr());
                        old.first->releaseSrfd(old.second, true);
                    }
                }
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
                    if (m_router->directionalSrfd()) {
                        auto &entry = m_srfd[vc];
                        entry.held = true;
                        entry.staging = true;
                        entry.admission_pending = true;
                        entry.dirty = msg->getSRFDDirty();
                        entry.address = msg->getaddr();
                        entry.sequence = m_router->nextSrfdSequence();
                        entry.stored_tick = curTick();
                        m_router->indexSrfd(entry.address, this, vc);
                    } else if (msg->getSRFDDirty()) {
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
                    entry.sequence = m_router->directionalSrfd() ?
                        m_router->nextSrfdSequence() : ++m_srfd_sequence;
                    entry.stored_tick = curTick();
                    if (m_router->directionalSrfd())
                        m_router->indexSrfd(entry.address, this, vc);
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
            if (m_srfd[vc].staging) {
                m_router->trySpill(this, vc);
            } else {
                if (m_srfd_clean_bypass[vc])
                    discardCleanPacket(vc);
                m_router->get_net_ptr()->getRubySystem()->completeSrfdStore(address);
                if (m_router->directionalSrfd()) m_router->retrySrfd(address);
                else retryWaitingSrfdRequests(address);
            }
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
    if (m_srfd_leases[in_vc]) {
        // These flits came from a local transfer, not the upstream link.
        if (free_signal) {
            update_vc_availability();
            ++m_free_vcs;
            assert(m_free_vcs <= m_router->get_num_vcs());
            const uint64_t lease = m_srfd_leases[in_vc];
            m_srfd_leases[in_vc] = 0;
            ++m_srfd_lease_releases;
            const int vnet = in_vc / m_vc_per_vnet;
            uint64_t reclaim = 0;
            if (m_srfd_reclaim_waiting[vnet] &&
                (m_srfd_reclaim_victim[vnet] == in_vc ||
                 m_srfd_reclaim_victim[vnet] < 0)) {
                reclaim = m_srfd_reclaim_epoch[vnet];
                m_srfd_reclaim_cycles.sample(
                    (curTick() - m_srfd_reclaim_start[vnet]) /
                    m_router->clockPeriod());
                m_srfd_reclaim_waiting[vnet] = false;
                m_srfd_reclaim_victim[vnet] = -1;
            }
            auto *upstream = m_srfd_upstream;
            upstream->router()->srfdControl(m_srfd_control_latency,
                [upstream, in_vc, lease, reclaim]() {
                    upstream->releaseSrfdLease(in_vc, lease, reclaim);
                });
        }
        return;
    }
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
        if (entry.held && !entry.staging && (!complete_only || entry.complete) &&
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
    assert(!entry.staging);
    if (m_router->directionalSrfd())
        m_router->eraseSrfd(entry.address, this, vc);
    m_srfd_residence_cycles.sample(
        (curTick() - entry.stored_tick) / m_router->clockPeriod());
    m_router->get_net_ptr()->getRubySystem()->recordSrfdEviction(
        entry.address);
    if (drop) {
        discardCleanPacket(vc);
        ++m_srfd_clean_dropped;
    } else {
        if (m_router->directionalSrfd()) markEscape(vc);
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
        stored += m_srfd[vc].held && m_srfd[vc].complete && !m_srfd[vc].staging;
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
        if (m_router->directionalSrfd() && !m_router->m_srfd_spill.source &&
            !m_srfd[victim].staging &&
            !m_router->get_net_ptr()->getRubySystem()->srfdStorePending(
                m_srfd[victim].address)) {
            m_router->get_net_ptr()->getRubySystem()->beginSrfdStore(
                m_srfd[victim].address);
            m_srfd[victim].staging = true;
            m_srfd[victim].previously_stored = true;
            update_srfd_occupancy();
            --m_srfd_stored_count;
            m_srfd_resident = m_srfd_stored_count;
            // Migration frees the VC after its tail is transferred. It is
            // not a block eviction or a successful pressure release.
            ++m_srfd_pressure_no_victim;
            m_router->trySpill(this, victim);
            return false;
        }
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
        m_router->get_net_ptr()->getRubySystem()->recordSrfdRequest(
            request_msg->getaddr());
        if (getx) ++m_srfd_getx_lookups; else ++m_srfd_gets_lookups;
    }
    if (m_router->get_net_ptr()->getRubySystem()->
        srfdStorePending(request_msg->getaddr())) {
        if (count_lookup) ++m_srfd_incomplete_misses;
        return SrfdRequestResult::Wait;
    }
    if (m_router->directionalSrfd()) {
        const auto location = m_router->findSrfd(request_msg->getaddr());
        if (location.first && location.first != this)
            return location.first->trySrfdRequest(request, false);
    }
    int match = -1;
    uint64_t oldest = std::numeric_limits<uint64_t>::max();
    bool incomplete = false;
    for (int vc = 0; vc < m_srfd.size(); ++vc) {
        const auto &entry = m_srfd[vc];
        if (!entry.held || entry.address != request_msg->getaddr()) continue;
        incomplete |= !entry.complete || entry.staging;
        if (entry.complete && !entry.staging && entry.sequence < oldest) {
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
    grant_outport(match, m_router->route_compute(route, m_id,
        m_router->directionalSrfd() ? "Local" : m_direction));
    if (m_router->directionalSrfd()) {
        // Every flit must carry the reply route and escape class.
        std::vector<flit*> packet;
        while (virtualChannels[match].isReady(curTick()))
            packet.push_back(virtualChannels[match].getTopFlit());
        for (auto *part : packet) {
            part->set_route(route);
            part->setSrfdEscape();
            virtualChannels[match].insertFlit(part);
        }
        m_router->eraseSrfd(m_srfd[match].address, this, match);
    }
    const uint64_t residence_cycles =
        (curTick() - m_srfd[match].stored_tick) / m_router->clockPeriod();
    m_srfd_residence_cycles.sample(residence_cycles);
    m_router->get_net_ptr()->getRubySystem()->recordSrfdReply(
        m_srfd[match].dirty, residence_cycles);
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
    m_srfd_opening_staged_offers_count = 0;
    m_srfd_opening_staged_kind[0] = m_srfd_opening_staged_kind[1] = 0;
    m_srfd_opening_leases_count = std::count_if(m_srfd_leases.begin(),
        m_srfd_leases.end(), [](uint64_t lease) { return lease != 0; });
    for (const auto &entry : m_srfd) {
        if (entry.held && entry.staging && entry.previously_stored)
            ++m_srfd_opening_count;
        if (entry.admission_pending) {
            ++m_srfd_opening_staged_offers_count;
            ++m_srfd_opening_staged_kind[entry.dirty];
        }
    }
    for (int i = 0; i <= m_router->get_num_vcs(); ++i)
        m_srfd_occupancy_cycles[i] = 0;
    // --- PAPER IMPLEMENTATION: Drop Fast-Forward Cycles ---
    if (m_direction == "Local" || m_router->directionalSrfd()) {
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
    m_srfd_opening_staged_offers.name(prefix + "opening_staged_offers");
    m_srfd_opening_staged_clean.name(prefix + "opening_staged_clean");
    m_srfd_opening_staged_dirty.name(prefix + "opening_staged_dirty");
    m_srfd_closing_staged_clean.name(prefix + "closing_staged_clean");
    m_srfd_closing_staged_dirty.name(prefix + "closing_staged_dirty");
    m_srfd_occupancy_cycles
        .init(m_router->get_num_vcs() + 1)
        .name(prefix + "occupancy_cycles")
        .desc("Cycles with exactly n SRFD packets resident")
        .flags(statistics::pdf);
    m_srfd_residence_cycles
        .init(0, 100000, 100)
        .name(prefix + "residence_cycles")
        .desc("SRFD storage residence time in router cycles");
    m_srfd_lease_requests.name(prefix + "lease_requests");
    m_srfd_lease_grants.name(prefix + "lease_grants");
    m_srfd_lease_denials.name(prefix + "lease_denials");
    m_srfd_lease_releases.name(prefix + "lease_releases");
    m_srfd_opening_leases.name(prefix + "opening_leases");
    m_srfd_closing_leases.name(prefix + "closing_leases");
    m_srfd_transfer_flits.name(prefix + "transfer_flits");
    m_srfd_reclaim_requests.name(prefix + "reclaim_requests");
    m_srfd_reclaim_releases.name(prefix + "reclaim_releases");
    m_srfd_reclaim_cycles.init(0, 999999, 1000)
        .name(prefix + "reclaim_cycles")
        .desc("Directional reclaim request to emptied-buffer cycles");
}

void
InputUnit::bindSrfd(OutputUnit *output, Cycles latency)
{
    m_srfd_upstream = output;
    m_srfd_control_latency = std::max(latency, Cycles(1));
}

void
InputUnit::borrowVc(int vc, uint64_t lease)
{
    fatal_if(m_srfd_leases[vc] || virtualChannels[vc].get_state() != IDLE_ ||
             virtualChannels[vc].isReady(curTick()) ||
             m_srfd_stored_count >= m_router->srfdStorageCapacity(),
             "SRFD lease granted to an unavailable destination VC");
    assert(!m_router->escapeVc(vc));
    m_srfd_leases[vc] = lease;
    set_vc_active(vc, curTick());
    update_vc_availability();
    --m_free_vcs;
    assert(m_free_vcs >= 0);
}

bool
InputUnit::copySpillFlit(InputUnit *source, int source_vc, int vc)
{
    assert(m_srfd_leases[vc]);
    auto &from = source->m_srfd[source_vc];
    auto &to = m_srfd[vc];
    assert(from.held && from.staging && from.complete);
    if (!to.held) {
        to = from;
        to.admission_pending = false;
        to.complete = false;
        update_srfd_occupancy();
        ++m_srfd_stored_count;
        if (!to.previously_stored) {
            if (to.dirty) ++m_srfd_dirty_stored;
            else ++m_srfd_clean_stored;
        }
        from.previously_stored = false;
        from.admission_pending = false;
        to.previously_stored = false;
        m_srfd_max_stored = std::max(m_srfd_max_stored.value(),
                                    (double)m_srfd_stored_count);
    }
    auto *part = source->virtualChannels[source_vc].getTopFlit();
    const bool tail = part->get_type() == TAIL_ || part->get_type() == HEAD_TAIL_;
    part->set_vc(vc);
    virtualChannels[vc].insertFlit(part);
    ++m_srfd_transfer_flits;
    const int vnet = vc / m_vc_per_vnet;
    ++m_num_buffer_writes[vnet];
    ++source->m_num_buffer_reads[vnet];
    source->increment_credit(source_vc, tail, curTick());
    if (!tail) return false;
    const Addr address = from.address;
    m_router->eraseSrfd(address, source, source_vc);
    source->m_srfd[source_vc] = SrfdEntry();
    source->set_vc_idle(source_vc, curTick());
    to.complete = true;
    to.staging = false;
    to.previously_stored = false;
    m_srfd_resident = m_srfd_stored_count;
    m_router->indexSrfd(address, this, vc);
    auto *head = virtualChannels[vc].peekTopFlit();
    grant_outport(vc, m_router->route_compute(head->get_route(), m_id, "Local"));
    m_router->get_net_ptr()->getRubySystem()->completeSrfdStore(address);
    m_router->retrySrfd(address);
    if (m_srfd_reclaim_waiting[vnet]) reclaimDirectional(vnet);
    return true;
}

void
InputUnit::fallbackSpill(int vc)
{
    const auto entry = m_srfd[vc];
    assert(entry.held && entry.staging && entry.complete);
    if (entry.previously_stored) {
        m_srfd[vc].staging = false;
        m_srfd[vc].previously_stored = false;
        update_srfd_occupancy();
        ++m_srfd_stored_count;
        ++m_srfd_pressure_attempts;
        ++m_srfd_pressure_events;
        // This delayed fallback is a separate pressure check, possibly in a
        // new ROI, rather than rewriting a counter before the stats reset.
        releaseSrfd(vc, !entry.dirty);
        m_router->get_net_ptr()->getRubySystem()->completeSrfdStore(entry.address);
        m_router->retrySrfd(entry.address);
        return;
    }
    m_router->eraseSrfd(entry.address, this, vc);
    m_srfd[vc] = SrfdEntry();
    if (entry.dirty) {
        ++m_srfd_dirty_bypassed;
        virtualChannels[vc].peekTopFlit()->advance_stage(SA_, curTick());
        m_router->schedule_wakeup(Cycles(1));
    } else {
        ++m_srfd_clean_bypassed;
        discardCleanPacket(vc);
    }
    m_router->get_net_ptr()->getRubySystem()->completeSrfdStore(entry.address);
    m_router->retrySrfd(entry.address);
}

void
InputUnit::markEscape(int vc)
{
    std::vector<flit*> packet;
    while (virtualChannels[vc].isReady(curTick()))
        packet.push_back(virtualChannels[vc].getTopFlit());
    assert(!packet.empty());
    for (auto *part : packet) {
        part->setSrfdEscape();
        virtualChannels[vc].insertFlit(part);
    }
    grant_outport(vc, m_router->route_compute(packet.front()->get_route(), m_id, "Local"));
}

void
InputUnit::reclaimDirectional(int vnet, uint64_t epoch)
{
    if (epoch) {
        if (epoch <= m_srfd_reclaim_epoch[vnet]) return;
        m_srfd_reclaim_epoch[vnet] = epoch;
    }
    if (!m_srfd_reclaim_waiting[vnet]) {
        ++m_srfd_reclaim_requests;
        m_srfd_reclaim_start[vnet] = curTick();
        m_srfd_reclaim_waiting[vnet] = true;
    }
    if (m_srfd_reclaim_victim[vnet] >= 0) return;
    const int victim = oldestStored(vnet);
    if (victim >= 0 && !m_srfd[victim].staging) {
        m_srfd_reclaim_victim[vnet] = victim;
        ++m_srfd_reclaim_releases;
        // Do not count this as a Local NI pressure attempt.
        releaseSrfd(victim, !m_srfd[victim].dirty);
        return;
    }
    // A grant/transfer or a dirty victim may still be draining. Keep its
    // lease pinned, and retry only after that work completes.
    for (int vc = vnet * m_vc_per_vnet; vc < (vnet + 1) * m_vc_per_vnet; ++vc)
        if (m_srfd_leases[vc]) return;
    m_srfd_reclaim_waiting[vnet] = false;
    auto *upstream = m_srfd_upstream;
    const uint64_t completed = m_srfd_reclaim_epoch[vnet];
    upstream->router()->srfdControl(m_srfd_control_latency,
        [upstream, vnet, completed]() { upstream->finishSrfdReclaim(vnet, completed); });
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
    if (m_direction == "Local" || m_router->directionalSrfd()) {
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
