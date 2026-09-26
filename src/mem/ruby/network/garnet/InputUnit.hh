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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__

#include <iostream>
#include <limits>
#include <vector>

//PRANJAL
#include "base/statistics.hh"

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/CreditLink.hh"
#include "mem/ruby/network/garnet/NetworkLink.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/network/garnet/VirtualChannel.hh"
#include "mem/ruby/network/garnet/flitBuffer.hh"

namespace gem5
{

namespace ruby
{

namespace garnet
{

class InputUnit : public Consumer
{
  public:
    InputUnit(int id, PortDirection direction, Router *router);
    ~InputUnit() = default;

    void wakeup();
    void print(std::ostream& out) const {};

    inline PortDirection get_direction() { return m_direction; }

    inline void
    set_vc_idle(int vc, Tick curTime)
    {
        virtualChannels[vc].set_idle(curTime);
    }

    inline void
    set_vc_active(int vc, Tick curTime)
    {
        virtualChannels[vc].set_active(curTime);
    }

    inline void
    grant_outport(int vc, int outport)
    {
        virtualChannels[vc].set_outport(outport);
    }

    inline void
    grant_outvc(int vc, int outvc)
    {
        virtualChannels[vc].set_outvc(outvc);
    }

    inline int
    get_outport(int invc)
    {
        return virtualChannels[invc].get_outport();
    }

    inline int
    get_outvc(int invc)
    {
        return virtualChannels[invc].get_outvc();
    }

    inline Tick
    get_enqueue_time(int invc)
    {
        return virtualChannels[invc].get_enqueue_time();
    }

    void increment_credit(int in_vc, bool free_signal, Tick curTime);

    inline flit*
    peekTopFlit(int vc)
    {
        return virtualChannels[vc].peekTopFlit();
    }

    inline flit*
    getTopFlit(int vc)
    {
        return virtualChannels[vc].getTopFlit();
    }

    inline bool
    need_stage(int vc, flit_stage stage, Tick time)
    {
        if (m_srfd[vc].held) return false;
        return virtualChannels[vc].need_stage(stage, time);
    }

    inline bool
    isReady(int invc, Tick curTime)
    {
        return virtualChannels[invc].isReady(curTime);
    }

    flitBuffer* getCreditQueue() { return &creditQueue; }

    inline void
    set_in_link(NetworkLink *link)
    {
        m_in_link = link;
    }

    inline int get_inlink_id() { return m_in_link->get_id(); }

    inline void
    set_credit_link(CreditLink *credit_link)
    {
        m_credit_link = credit_link;
    }

    double get_buf_read_activity(unsigned int vnet) const
    { return m_num_buffer_reads[vnet]; }
    double get_buf_write_activity(unsigned int vnet) const
    { return m_num_buffer_writes[vnet]; }

    //PRANJAL
    uint64_t get_local_packets_generated() const { return m_local_packets_generated; }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *pkt);

    void resetStats();
    //PRANJAL paper
    void regStats();
  private:
    struct SrfdEntry {
        bool held = false;
        bool complete = false;
        bool dirty = false;
        Addr address = 0;
        uint64_t sequence = 0;
        Tick stored_tick = 0;
    };

    bool trySrfdRequest(flit *request);
    void releaseSrfd(int vc, bool drop);
    void applySrfdPressure(int vnet);
    int oldestStored(int vnet, bool complete_only = true) const;
    void returnDroppedRequestCredit(int vc);
    //PRANJAL
    bool isLocalPacket() const {
        return m_direction == "Local";
    }

    Router *m_router;
    int m_id;
    PortDirection m_direction;
    int m_vc_per_vnet;
    NetworkLink *m_in_link;
    CreditLink *m_credit_link;
    flitBuffer creditQueue;
    //PRANJAL
    uint64_t m_local_packets_generated;
    //PRANJAL PAPER
    // --- PAPER IMPLEMENTATION: VC Availability Tracking ---
    int m_free_vcs;
    uint64_t m_last_vc_update_cycle;
    gem5::statistics::Vector vc_availability_stat; 

    void update_vc_availability();
    //PRANJAL end
    // Input Virtual channels
    std::vector<VirtualChannel> virtualChannels;
    std::vector<SrfdEntry> m_srfd;
    uint64_t m_srfd_sequence = 0;
    unsigned m_srfd_stored_count = 0;

    statistics::Scalar m_srfd_dirty_offered;
    statistics::Scalar m_srfd_clean_offered;
    statistics::Scalar m_srfd_dirty_stored;
    statistics::Scalar m_srfd_clean_stored;
    statistics::Scalar m_srfd_dirty_forwarded;
    statistics::Scalar m_srfd_clean_dropped;
    statistics::Scalar m_srfd_gets_lookups;
    statistics::Scalar m_srfd_getx_lookups;
    statistics::Scalar m_srfd_clean_hits;
    statistics::Scalar m_srfd_dirty_hits;
    statistics::Scalar m_srfd_getx_clean_conflicts;
    statistics::Scalar m_srfd_incomplete_misses;
    statistics::Scalar m_srfd_pressure_events;
    statistics::Scalar m_srfd_avoided_requests;
    statistics::Scalar m_srfd_max_stored;
    statistics::Distribution m_srfd_residence_cycles;

    // Statistical variables
    std::vector<double> m_num_buffer_writes;
    std::vector<double> m_num_buffer_reads;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_INPUTUNIT_HH__
