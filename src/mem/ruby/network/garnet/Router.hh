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


#ifndef __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__
#define __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__

#include <iostream>
#include <memory>
#include <vector>
#include <functional>
#include <map>
#include <unordered_map>

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/NetDest.hh"
#include "mem/ruby/network/BasicRouter.hh"
#include "mem/ruby/network/garnet/CommonTypes.hh"
#include "mem/ruby/network/garnet/CrossbarSwitch.hh"
#include "mem/ruby/network/garnet/GarnetNetwork.hh"
#include "mem/ruby/network/garnet/RoutingUnit.hh"
#include "mem/ruby/network/garnet/SwitchAllocator.hh"
#include "mem/ruby/network/garnet/flit.hh"
#include "params/GarnetRouter.hh"

namespace gem5
{

namespace ruby
{

class FaultModel;

namespace garnet
{

class NetworkLink;
class CreditLink;
class InputUnit;
class OutputUnit;

class Router : public BasicRouter, public Consumer
{
  public:
    enum class SrfdMode { Baseline, DbDefensive, DbAggressive,
        CbDbDefensive, CbDbAggressive, CbDbNoCorner };

    typedef GarnetRouterParams Params;
    Router(const Params &p);

    ~Router() = default;

    void wakeup();
    void print(std::ostream& out) const {};

    void init();
    int addInPort(PortDirection inport_dirn, NetworkLink *link,
                  CreditLink *credit_link);
    void addOutPort(PortDirection outport_dirn, NetworkLink *link,
                    std::vector<NetDest>& routing_table_entry,
                    int link_weight, CreditLink *credit_link,
                    uint32_t consumerVcs);

    Cycles get_pipe_stages(){ return m_latency; }
    uint32_t get_num_vcs()       { return m_num_vcs; }
    uint32_t get_num_vnets()     { return m_virtual_networks; }
    uint32_t get_vc_per_vnet()   { return m_vc_per_vnet; }
    int get_num_inports()   { return m_input_unit.size(); }
    int get_num_outports()  { return m_output_unit.size(); }
    int get_id()            { return m_id; }
    SrfdMode getSrfdMode() const { return m_srfd_mode; }
    bool srfdEnabled() const { return m_srfd_mode != SrfdMode::Baseline; }
    bool srfdStoresClean() const;
    bool srfdDefensive() const;
    bool srfdDisabledAtThisRouter() const;
    uint32_t srfdStorageCapacity() const
    { return m_vc_per_vnet - m_srfd_reserved_vcs; }
    bool applySrfdPressure(int inport, int vnet);
    bool directionalSrfd() const { return m_srfd_directional; }
    bool escapeVc(int vc) const
    { return m_srfd_directional && vc % m_vc_per_vnet == m_vc_per_vnet - 1 &&
             m_network_ptr->get_vnet_type(vc / m_vc_per_vnet) == DATA_VNET_; }
    uint64_t nextSrfdSequence() { return ++m_srfd_sequence; }
    std::pair<InputUnit*, int> findSrfd(Addr address);
    void indexSrfd(Addr address, InputUnit *input, int vc);
    void eraseSrfd(Addr address, InputUnit *input, int vc);
    void srfdControl(Cycles delay, std::function<void()> callback);
    void trySpill(InputUnit *source, int vc);
    void advanceSpill();
    void retrySrfd(Addr address);
    bool srfdTransient() const;

    void init_net_ptr(GarnetNetwork* net_ptr)
    {
        m_network_ptr = net_ptr;
    }

    GarnetNetwork* get_net_ptr()                    { return m_network_ptr; }

    InputUnit*
    getInputUnit(unsigned port)
    {
        assert(port < m_input_unit.size());
        return m_input_unit[port].get();
    }

    OutputUnit*
    getOutputUnit(unsigned port)
    {
        assert(port < m_output_unit.size());
        return m_output_unit[port].get();
    }

    int getBitWidth() { return m_bit_width; }

    PortDirection getOutportDirection(int outport);
    PortDirection getInportDirection(int inport);

    int route_compute(RouteInfo route, int inport, PortDirection direction);
    void grant_switch(int inport, flit *t_flit);
    void schedule_wakeup(Cycles time);

    std::string getPortDirectionName(PortDirection direction);
    void printFaultVector(std::ostream& out);
    void printAggregateFaultProbability(std::ostream& out);

    void regStats();
    void collateStats();
    void resetStats();

    // For Fault Model:
    bool get_fault_vector(int temperature, float fault_vector[]) {
        return m_network_ptr->fault_model->fault_vector(m_id, temperature,
                                                        fault_vector);
    }
    bool get_aggregate_fault_probability(int temperature,
                                         float *aggregate_fault_prob) {
        return m_network_ptr->fault_model->fault_prob(m_id, temperature,
                                                      aggregate_fault_prob);
    }

    bool functionalRead(Packet *pkt, WriteMask &mask);
    uint32_t functionalWrite(Packet *);

  private:
    friend class InputUnit;
    Cycles m_latency;
    uint32_t m_virtual_networks, m_vc_per_vnet, m_num_vcs;
    uint32_t m_bit_width;
    SrfdMode m_srfd_mode;
    uint32_t m_srfd_reserved_vcs;
    bool m_srfd_directional;
    uint64_t m_srfd_sequence = 0;
    unsigned m_srfd_direction_cursor = 0;
    std::unordered_map<Addr, std::pair<InputUnit*, int>> m_srfd_index;
    std::multimap<Tick, std::function<void()>> m_srfd_control;
    struct Spill {
        InputUnit *source = nullptr;
        int source_vc = -1;
        InputUnit *destination = nullptr;
        int destination_vc = -1;
        std::vector<InputUnit*> candidates;
        unsigned next = 0;
        bool awaiting = false;
    } m_srfd_spill;
    int m_mesh_rows;
    GarnetNetwork *m_network_ptr;

    RoutingUnit routingUnit;
    SwitchAllocator switchAllocator;
    CrossbarSwitch crossbarSwitch;

    std::vector<std::shared_ptr<InputUnit>> m_input_unit;
    std::vector<std::shared_ptr<OutputUnit>> m_output_unit;

    // Statistical variables required for power computations
    statistics::Scalar m_buffer_reads;
    statistics::Scalar m_buffer_writes;

    statistics::Scalar m_sw_input_arbiter_activity;
    statistics::Scalar m_sw_output_arbiter_activity;

    statistics::Scalar m_crossbar_activity;
    //PRANJAL
    statistics::Scalar m_local_packets_generated;
};

} // namespace garnet
} // namespace ruby
} // namespace gem5

#endif // __MEM_RUBY_NETWORK_GARNET_0_ROUTER_HH__
