/*
 * Copyright (c) 2008 Princeton University
 * Copyright (c) 2016 Georgia Institute of Technology
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


#include "mem/ruby/network/garnet/RoutingUnit.hh"
// #include <iostream>
#include "base/cast.hh"
#include "base/compiler.hh"
#include "debug/RubyNetwork.hh"
#include "mem/ruby/network/garnet/InputUnit.hh"
#include "mem/ruby/network/garnet/Router.hh"
#include "mem/ruby/slicc_interface/Message.hh"
#include "mem/ruby/network/garnet/OutputUnit.hh"
namespace gem5
{

namespace ruby
{

namespace garnet
{

RoutingUnit::RoutingUnit(Router *router)
{
    m_router = router;
    m_routing_table.clear();
    m_weight_table.clear();
}

void
RoutingUnit::addRoute(std::vector<NetDest>& routing_table_entry)
{
    if (routing_table_entry.size() > m_routing_table.size()) {
        m_routing_table.resize(routing_table_entry.size());
    }
    for (int v = 0; v < routing_table_entry.size(); v++) {
        m_routing_table[v].push_back(routing_table_entry[v]);
    }
}

void
RoutingUnit::addWeight(int link_weight)
{
    m_weight_table.push_back(link_weight);
}

bool
RoutingUnit::supportsVnet(int vnet, std::vector<int> sVnets)
{
    // If all vnets are supported, return true
    if (sVnets.size() == 0) {
        return true;
    }

    // Find the vnet in the vector, return true
    if (std::find(sVnets.begin(), sVnets.end(), vnet) != sVnets.end()) {
        return true;
    }

    // Not supported vnet
    return false;
}

/*
 * This is the default routing algorithm in garnet.
 * The routing table is populated during topology creation.
 * Routes can be biased via weight assignments in the topology file.
 * Correct weight assignments are critical to provide deadlock avoidance.
 */
int
RoutingUnit::lookupRoutingTable(int vnet, NetDest msg_destination)
{
    // First find all possible output link candidates
    // For ordered vnet, just choose the first
    // (to make sure different packets don't choose different routes)
    // For unordered vnet, randomly choose any of the links
    // To have a strict ordering between links, they should be given
    // different weights in the topology file

    int output_link = -1;
    int min_weight = INFINITE_;
    std::vector<int> output_link_candidates;
    int num_candidates = 0;

    // Identify the minimum weight among the candidate output links
    for (int link = 0; link < m_routing_table[vnet].size(); link++) {
        if (msg_destination.intersectionIsNotEmpty(
            m_routing_table[vnet][link])) {

        if (m_weight_table[link] <= min_weight)
            min_weight = m_weight_table[link];
        }
    }

    // Collect all candidate output links with this minimum weight
    for (int link = 0; link < m_routing_table[vnet].size(); link++) {
        if (msg_destination.intersectionIsNotEmpty(
            m_routing_table[vnet][link])) {

            if (m_weight_table[link] == min_weight) {
                num_candidates++;
                output_link_candidates.push_back(link);
            }
        }
    }

    if (output_link_candidates.size() == 0) {
        fatal("Fatal Error:: No Route exists from this Router.");
        exit(0);
    }

    // Randomly select any candidate output link
    int candidate = 0;
    if (!(m_router->get_net_ptr())->isVNetOrdered(vnet))
        candidate = rand() % num_candidates;

    output_link = output_link_candidates.at(candidate);
    return output_link;
}


void
RoutingUnit::addInDirection(PortDirection inport_dirn, int inport_idx)
{
    m_inports_dirn2idx[inport_dirn] = inport_idx;
    m_inports_idx2dirn[inport_idx]  = inport_dirn;
}

void
RoutingUnit::addOutDirection(PortDirection outport_dirn, int outport_idx)
{
    m_outports_dirn2idx[outport_dirn] = outport_idx;
    m_outports_idx2dirn[outport_idx]  = outport_dirn;
}

// outportCompute() is called by the InputUnit
// It calls the routing table by default.
// A template for adaptive topology-specific routing algorithm
// implementations using port directions rather than a static routing
// table is provided here.

int
RoutingUnit::outportCompute(RouteInfo route, int inport,
                            PortDirection inport_dirn)
{
    int outport = -1;

    if (route.dest_router == m_router->get_id()) {

        // Multiple NIs may be connected to this router,
        // all with output port direction = "Local"
        // Get exact outport id from table
        outport = lookupRoutingTable(route.vnet, route.net_dest);
        return outport;
    }

    // Routing Algorithm set in GarnetNetwork.py
    // Can be over-ridden from command line using --routing-algorithm = 1
    RoutingAlgorithm routing_algorithm =
        (RoutingAlgorithm) m_router->get_net_ptr()->getRoutingAlgorithm();
    ///PRANJAL
        static bool printed_algorithm = false;

    if (!printed_algorithm && m_router->get_id() == 0) {
        const char* name;

        switch (routing_algorithm) {
            case TABLE_:     name = "TABLE"; break;
            case XY_:        name = "XY"; break;
            case CUSTOM_:    name = "CUSTOM"; break;
            case ODD_EVEN_:  name = "ODD_EVEN"; break;
            case DYXY_:      name = "DYXY"; break;
            default:         name = "UNKNOWN"; break;
        }

        std::cout << "\n========================================\n"
                << " Routing Algorithm: " << name << "\n"
                << "========================================\n\n";

        printed_algorithm = true;
    }
    ///////
    switch (routing_algorithm) {
        case TABLE_:  outport =
            lookupRoutingTable(route.vnet, route.net_dest); break;
        case XY_:     outport =
            outportComputeXY(route, inport, inport_dirn); break;
        // any custom algorithm
        case CUSTOM_: outport =
            outportComputeCustom(route, inport, inport_dirn); break;
        case ODD_EVEN_: outport =
            outportComputeOddEven(route, inport, inport_dirn); break;
        case DYXY_: outport =
            outportComputeDYXY(route, inport, inport_dirn); break;
        default: outport =
            lookupRoutingTable(route.vnet, route.net_dest); break;
    }

    assert(outport != -1);
    return outport;
}

// XY routing implemented using port directions
// Only for reference purpose in a Mesh
// By default Garnet uses the routing table
int
RoutingUnit::outportComputeXY(RouteInfo route,
                              int inport,
                              PortDirection inport_dirn)
{
    PortDirection outport_dirn = "Unknown";

    [[maybe_unused]] int num_rows = m_router->get_net_ptr()->getNumRows();
    int num_cols = m_router->get_net_ptr()->getNumCols();
    assert(num_rows > 0 && num_cols > 0);

    int my_id = m_router->get_id();
    int my_x = my_id % num_cols;
    int my_y = my_id / num_cols;

    int dest_id = route.dest_router;
    int dest_x = dest_id % num_cols;
    int dest_y = dest_id / num_cols;

    int x_hops = abs(dest_x - my_x);
    int y_hops = abs(dest_y - my_y);

    bool x_dirn = (dest_x >= my_x);
    bool y_dirn = (dest_y >= my_y);

    // already checked that in outportCompute() function
    assert(!(x_hops == 0 && y_hops == 0));

    if (x_hops > 0) {
        if (x_dirn) {
            assert(inport_dirn == "Local" || inport_dirn == "West");
            outport_dirn = "East";
        } else {
            assert(inport_dirn == "Local" || inport_dirn == "East");
            outport_dirn = "West";
        }
    } else if (y_hops > 0) {
        if (y_dirn) {
            // "Local" or "South" or "West" or "East"
            assert(inport_dirn != "North");
            outport_dirn = "North";
        } else {
            // "Local" or "North" or "West" or "East"
            assert(inport_dirn != "South");
            outport_dirn = "South";
        }
    } else {
        // x_hops == 0 and y_hops == 0
        // this is not possible
        // already checked that in outportCompute() function
        panic("x_hops == y_hops == 0");
    }

    return m_outports_dirn2idx[outport_dirn];
}
//PRANJAL
// int
// RoutingUnit::outportComputeOddEven(RouteInfo route,
//                                    int inport,
//                                    PortDirection inport_dirn)
// {
//     PortDirection outport_dirn = "Unknown";
//     int num_cols = m_router->get_net_ptr()->getNumCols();

//     // Current node: (c_0, c_1) -> (Cx, Cy)
//     int my_id = m_router->get_id();
//     int Cx = my_id % num_cols;
//     int Cy = my_id / num_cols;

//     // Source node: (s_0, s_1) -> (Sx, Sy)
//     int source_id = route.src_router;
//     int Sx = source_id % num_cols;
//     int Sy = source_id / num_cols;
//     // Destination node: (d_0, d_1) -> (Dx, Dy)
//     int dest_id = route.dest_router;
//     int Dx = dest_id % num_cols;
//     int Dy = dest_id / num_cols;

//     // Displacements: e_0, e_1 -> Ex, Ey
//     int Ex = Dx - Cx;
//     int Ey = Dy - Cy;

//     // if (e_0 = 0 and e_1 = 0) Deliver the packet to the local node and exit;
//     assert(!(Ex == 0 && Ey == 0)); // Local delivery is handled before outportCompute in Garnet

//     // Avail_Dimension_Set <--- Empty
//     bool avail_E = false;
//     bool avail_W = false;
//     bool avail_N = false;
//     bool avail_S = false;

//     // if (e_0 = 0) /* currently in the same column as destination */
//     if (Ex == 0) { 
//         if (Ey < 0) {
//             avail_S = true; // Add South to Avail_Dimension_Set;
//         } else {
//             avail_N = true; // Add North to Avail_Dimension_Set;
//         }
//     } 
//     else {
//         // if (e_0 > 0) /* eastbound messages */
//         if (Ex > 0) { 
//             // if (e_1 = 0)
//             if (Ey == 0) { 
//                 avail_E = true; // Add East to Avail_Dimension_Set;
//             } 
//             else {
//                 // if (c_0 is odd or c_0 = s_0) 
//                 // Note: inport_dirn == "Local" perfectly identifies the source node (s_0)
//                 if ((Cx % 2 != 0) || (Cx == Sx)) {
//                     if (Ey < 0) {
//                         avail_S = true; // Add South to Avail_Dimension_Set;
//                     } else {
//                         avail_N = true; // Add North to Avail_Dimension_Set;
//                     }
//                 }
                
//                 // if (d_0 is odd or e_0 != 1) /* odd destination column or >= 2 columns */
//                 if ((Dx % 2 != 0) || (Ex != 1)) {
//                     avail_E = true; // Add East to Avail_Dimension_Set;
//                 }
//             }
//         } 
//         else { 
//             // else /* westbound messages */
//             avail_W = true; // Add West to Avail_Dimension_Set;
            
//             // if (c_0 is even)
//             // (Safety check added: && Ey != 0 prevents non-minimal routing on the same row)
//             if ((Cx % 2 == 0) && (Ey != 0)) {
//                 if (Ey < 0) {
//                     avail_S = true; // Add South to Avail_Dimension_Set;
//                 } else {
//                     avail_N = true; // Add North to Avail_Dimension_Set;
//                 }
//             }
//         }
//     }

//     // Select a dimension from Avail_Dimension_Set to forward the packet;
//     bool can_go_x = (avail_E || avail_W);
//     bool can_go_y = (avail_N || avail_S);
    
//     PortDirection x_dir = avail_E ? "East" : "West";
//     PortDirection y_dir = avail_N ? "North" : "South";

//     if (can_go_x && can_go_y) {
        
//         // =================================================================
//         // DETERMINISTIC TIE-BREAKER: Select X first, then Y
//         // =================================================================
//         // outport_dirn = x_dir; 
        
//         // =================================================================
//         // ADAPTIVE TIE-BREAKER (Commented out as requested)
//         // =================================================================
        
//         // int outport_x = m_outports_dirn2idx[x_dir];
//         // int outport_y = m_outports_dirn2idx[y_dir];
        
//         // int credits_x = getCongestionMetric(outport_x);
//         // int credits_y = getCongestionMetric(outport_y);
        
//         // if (credits_x > credits_y) {
//         //     outport_dirn = x_dir;
//         // } else if (credits_y > credits_x) {
//         //     outport_dirn = y_dir;
//         // } else {
//         //     outport_dirn = x_dir; // Default to X on tie
//         // }
        
//         // =================================================================

//     } else if (can_go_x) {
//         outport_dirn = x_dir;
//     } else if (can_go_y) {
//         outport_dirn = y_dir;
//     } else {
//         assert(false && "Deadlock trap: No valid dimension in Avail_Dimension_Set!");
//     }

//     assert(outport_dirn != "Unknown");
//     return m_outports_dirn2idx[outport_dirn];
// }

// ODD-EVEN
int
RoutingUnit::outportComputeOddEven(RouteInfo route,
                              int inport,
                              PortDirection inport_dirn)
{
    PortDirection outport_dirn = "Unknown";
    int num_cols = m_router->get_net_ptr()->getNumCols();
    int my_id = m_router->get_id();
    int my_x = my_id % num_cols;
    int my_y = my_id / num_cols;
    int dest_id = route.dest_router;
    int dest_x = dest_id % num_cols;
    int dest_y = dest_id / num_cols;

    int x_hops = abs(dest_x - my_x);
    int y_hops = abs(dest_y - my_y);
    bool x_dirn = (dest_x >= my_x);
    bool y_dirn = (dest_y >= my_y);

    if (x_hops == 0) {
        outport_dirn = y_dirn ? "North" : "South";
    } else if (y_hops == 0) {
        outport_dirn = x_dirn ? "East" : "West";
    } else {
        std::vector<PortDirection> valid_ports;
        
        if (x_dirn) { 
            // Moving East: East->North and East->South forbidden at Even columns
            if (my_x % 2 != 0 || my_x == dest_x) {
                valid_ports.push_back(y_dirn ? "North" : "South");
            }
            if (dest_x % 2 != 0 || x_hops != 1) {
                valid_ports.push_back("East");
            }
        } else { 
            // Moving West: North->West and South->West forbidden at Odd columns
            valid_ports.push_back("West");
            if (my_x % 2 == 0) {
                valid_ports.push_back(y_dirn ? "North" : "South");
            }
        }

        // Adaptive Selection based on queue congestion
        // int max_credits = -1;
        // for (const auto& port : valid_ports) {
        //     int credits = getFreeCredits(port, route.vnet);
        //     if (credits > max_credits) {
        //         max_credits = credits;
        //         outport_dirn = port;
        //     }
        // }
        // Adaptive Selection based on queue congestion
        int max_credits = -1;
        std::vector<PortDirection> best_ports;

        for (const auto& port : valid_ports) {
            int credits = getFreeCredits(port, route.vnet);
            if (credits > max_credits) {
                max_credits = credits;
                best_ports.clear();
                best_ports.push_back(port);
            } else if (credits == max_credits) {
                best_ports.push_back(port); // Collect tied ports
            }
        }

        // Break ties randomly to prevent deterministic asymmetric routing
        if (best_ports.size() > 1) {
            outport_dirn = best_ports[rand() % best_ports.size()];
        } else {
            outport_dirn = best_ports[0];
        }

    }
    
    return m_outports_dirn2idx[outport_dirn];
}

int
RoutingUnit::outportComputeDYXY(RouteInfo route,
                                int inport,
                                PortDirection inport_dirn)
{
    PortDirection outport_dirn = "Unknown";

    int num_cols = m_router->get_net_ptr()->getNumCols();

    // Current router (Cx, Cy)
    int my_id = m_router->get_id();
    int Cx = my_id % num_cols;
    int Cy = my_id / num_cols;

    // Destination router (Dx, Dy)
    int dest_id = route.dest_router;
    int Dx = dest_id % num_cols;
    int Dy = dest_id / num_cols;

    int dx = Dx - Cx;
    int dy = Dy - Cy;

    assert(!(dx == 0 && dy == 0));

    // 1. Destination in same column -> Force Y direction
    if (dx == 0) {
        outport_dirn = (dy > 0) ? "North" : "South";
    }
    // 2. Destination in same row -> Force X direction
    else if (dy == 0) {
        outport_dirn = (dx > 0) ? "East" : "West";
    }
    // 3. Both X and Y directions are valid minimal paths
    else {
        PortDirection x_candidate = (dx > 0) ? "East" : "West";
        PortDirection y_candidate = (dy > 0) ? "North" : "South";

        int outport_x = m_outports_dirn2idx[x_candidate];
        int outport_y = m_outports_dirn2idx[y_candidate];

        // Retrieve stress/congestion values for both candidate neighbors
        // int stress_x = getCongestionMetric(outport_x);
        // int stress_y = getCongestionMetric(outport_y);
        int stress_x = getFreeCredits(x_candidate,route.vnet);
        int stress_y = getFreeCredits(y_candidate,route.vnet);

        // Select neighbor with the smallest stress value
        if (stress_x > stress_y) {
            outport_dirn = x_candidate;
        } else if (stress_y > stress_x) {
            outport_dirn = y_candidate;
        } else {
            // Tie-breaker when stress values are equal (e.g., default X-first)
            outport_dirn = x_candidate;
        }
    }

    assert(outport_dirn != "Unknown");
    return m_outports_dirn2idx[outport_dirn];
}

// DyXY
// int
// RoutingUnit::outportComputeDYXY(RouteInfo route,
//                                 int inport,
//                                 PortDirection inport_dirn)
// {
//     PortDirection outport_dirn = "Unknown";
//     int num_cols = m_router->get_net_ptr()->getNumCols();
//     int my_id = m_router->get_id();
//     int my_x = my_id % num_cols;
//     int my_y = my_id / num_cols;
//     int dest_id = route.dest_router;
//     int dest_x = dest_id % num_cols;
//     int dest_y = dest_id / num_cols;

//     if (my_x == dest_x) {
//         outport_dirn = (dest_y > my_y) ? "North" : "South";
//     } else if (my_y == dest_y) {
//         outport_dirn = (dest_x > my_x) ? "East" : "West";
//     } else {
//         // Diagonal Adaptive Evaluation
//         PortDirection dir_x = (dest_x > my_x) ? "East" : "West";
//         PortDirection dir_y = (dest_y > my_y) ? "North" : "South";

//         int credits_x = getFreeCredits(dir_x, route.vnet);
//         int credits_y = getFreeCredits(dir_y, route.vnet);

//         if (credits_x > credits_y) {
//             outport_dirn = dir_x;
//         } else if (credits_y > credits_x) {
//             outport_dirn = dir_y;
//         } else {
//             outport_dirn = dir_x; // Tie-breaker
//         }
//     }

//     return m_outports_dirn2idx[outport_dirn];
// }

int
RoutingUnit::getFreeCredits(PortDirection dirn, int vnet)
{
    if (m_outports_dirn2idx.find(dirn) == m_outports_dirn2idx.end()) {
        return 0; // Port doesn't exist
    }
    
    int outport_idx = m_outports_dirn2idx[dirn];
    OutputUnit* out_unit = m_router->getOutputUnit(outport_idx);
    
    int total_credits = 0;
    
    // Rigorous Vnet isolation: Only poll VCs belonging to the current vnet
    int vcs_per_vnet = m_router->get_vc_per_vnet();
    int start_vc = vnet * vcs_per_vnet;
    int end_vc = start_vc + vcs_per_vnet;
    
    for (int vc = start_vc; vc < end_vc; vc++) {
        total_credits += out_unit->get_credit_count(vc);
    }
    
    return total_credits;
}
int
RoutingUnit::getCongestionMetric(int outport)const 
{
    // Retrieve the OutputUnit for this specific port
    OutputUnit* out_unit = m_router->getOutputUnit(outport);
    
    if (out_unit) {
        // Returns the sum of all available credits across VCs
        return out_unit->get_total_credit_count();
    }
    
    // Fallback if something goes wrong (zero credits = max stress)
    return 0; 
}

// Template for implementing custom routing algorithm
// using port directions. (Example adaptive)
int
RoutingUnit::outportComputeCustom(RouteInfo route,
                                 int inport,
                                 PortDirection inport_dirn)
{
    panic("%s placeholder executed", __FUNCTION__);
}

} // namespace garnet
} // namespace ruby
} // namespace gem5
