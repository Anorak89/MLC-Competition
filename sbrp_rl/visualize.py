import sys
import os
import argparse
import random
import numpy as np
import torch
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Import env and agents
from sbrp_env import SchoolBusRoutingEnv
from agents import RandomAgent, NearestNeighborAgent, ORToolsStaticAgent
from train import DQNAgent

# Set styling
plt.style.use('dark_background')
GRID_COLOR = '#1e293b'
ACCENT_COLOR = '#38bdf8'
TEXT_COLOR = '#f8fafc'

class SimulationVisualizer:
    def __init__(self, agent_type="nn", seed=42):
        self.seed = seed
        self.agent_type = agent_type
        
        # Initialize env
        self.env = SchoolBusRoutingEnv()
        self.nodes = self.env.nodes_data
        self.edges = self.env.edges_data
        
        # Select Agent
        if agent_type == "random":
            self.agent = RandomAgent()
        elif agent_type == "nn":
            self.agent = NearestNeighborAgent()
        elif agent_type == "static":
            self.agent = ORToolsStaticAgent()
        elif agent_type == "dqn":
            # Load trained DQN if it exists, otherwise fall back to NN
            model_path = "models/dqn_dispatcher.pth"
            obs_dict, _ = self.env.reset(seed=seed)
            flat_obs = self.env.get_flat_observation(obs_dict)
            state_dim = flat_obs.shape[0]
            action_dim = self.env.num_actions
            
            self.agent = DQNAgent(state_dim, action_dim)
            if os.path.exists(model_path):
                print(f"Loading trained DQN from {model_path}...")
                self.agent.load(model_path)
                self.agent.epsilon = 0.0 # pure evaluation
            else:
                print(f"Trained model not found at {model_path}! Please run train.py first. Falling back to Nearest Neighbor.")
                self.agent = NearestNeighborAgent()
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

        # Run the complete episode first to collect detailed tick history
        self._generate_episode_history()
        
    def _generate_episode_history(self):
        print(f"Generating episode history using {self.agent.name}...")
        obs_dict, info = self.env.reset(seed=self.seed)
        
        agent_reset = getattr(self.agent, "reset", None)
        if agent_reset:
            self.agent.reset()
            
        terminated = False
        truncated = False
        
        step_count = 0
        while not (terminated or truncated):
            active_bus_idx = obs_dict["active_bus_idx"]
            action_mask = obs_dict["action_mask"]
            
            if isinstance(self.agent, DQNAgent):
                # DQN Evaluation
                state_flat = self.env.get_flat_observation(obs_dict)
                state_t = torch.FloatTensor(state_flat).unsqueeze(0).to(self.agent.device)
                self.agent.policy_net.eval()
                with torch.no_grad():
                    q_values = self.agent.policy_net(state_t).cpu().numpy()[0]
                q_values[action_mask == 0.0] = -1e9
                action = int(np.argmax(q_values))
            else:
                action = self.agent.decide(obs_dict, info, self.env)
                
            obs_dict, reward, terminated, truncated, info = self.env.step(action)
            step_count += 1
            
        self.history = self.env.state_history
        self.final_metrics = info
        self.final_vrp_reward = self.env.compute_final_reward()
        
        print(f"Episode simulated in {step_count} decisions. Total ticks: {len(self.history)}")
        print(f"Final VRP Reward: {self.final_vrp_reward}")
        print(f"Delivered: {info['delivered_count']} / {self.env.num_students}")
        print(f"Mileage: {info['total_distance']:.2f} miles | Equity variance: {info['equity_variance']:.2f}")

    def start_animation(self):
        # Create figure with 2 subplots: Map (left) and Dashboard (right)
        fig = plt.figure(figsize=(15, 9), facecolor='#0f172a')
        
        # Grid layout
        gs = fig.add_gridspec(1, 2, width_ratios=[2.2, 1.0])
        
        ax_map = fig.add_subplot(gs[0], facecolor='#0f172a')
        ax_dash = fig.add_subplot(gs[1], facecolor='#1e293b')
        ax_dash.axis('off')
        
        # --- 1. PLOT STATIC MAP COMPONENTS ---
        ax_map.set_title(f"Hackensack School Bus Routing ({self.agent.name})", color=TEXT_COLOR, fontsize=14, fontweight='bold', pad=15)
        
        # Draw roads (edges)
        edge_plots = {}
        for edge in self.edges:
            u, v = edge["from"], edge["to"]
            n_u = self.nodes[u]
            n_v = self.nodes[v]
            
            # Default style: thin dark gray
            line, = ax_map.plot(
                [n_u["lng"], n_v["lng"]], 
                [n_u["lat"], n_v["lat"]], 
                color='#334155', 
                linewidth=1.2, 
                alpha=0.6, 
                zorder=1
            )
            # Map edge keys for dynamic updating
            edge_plots[(u, v)] = line
            edge_plots[(v, u)] = line

        # Plot school nodes
        school_colors = {"school_hhs": "#ef4444", "school_hms": "#22c55e", "school_fes": "#eab308"}
        school_markers = {}
        for sch_id, sch in self.env.schools_data.items():
            n_sch = self.nodes[sch["node"]]
            marker = ax_map.scatter(
                n_sch["lng"], 
                n_sch["lat"], 
                color=school_colors[sch_id], 
                marker='s', 
                s=180, 
                edgecolors=TEXT_COLOR, 
                linewidths=1.5,
                label=sch["name"],
                zorder=4
            )
            school_markers[sch_id] = marker

        # Plot depot node
        n_depot = self.nodes[self.env.depots_data["depot_1"]["node"]]
        ax_map.scatter(
            n_depot["lng"], 
            n_depot["lat"], 
            color='#64748b', 
            marker='o', 
            s=130, 
            edgecolors=TEXT_COLOR, 
            linewidths=1.5, 
            label="Bus Yard (Depot)",
            zorder=4
        )

        # Labels & bounds
        ax_map.set_xlim(self.env.lng_bounds[0] - 0.005, self.env.lng_bounds[1] + 0.005)
        ax_map.set_ylim(self.env.lat_bounds[0] - 0.003, self.env.lat_bounds[1] + 0.003)
        ax_map.xaxis.set_visible(False)
        ax_map.yaxis.set_visible(False)
        
        # Legend (top left)
        ax_map.legend(loc='upper left', facecolor='#0f172a', edgecolor='#1e293b', labelcolor=TEXT_COLOR, fontsize=9)

        # --- 2. DYNAMIC ELEMENTS PREPARATION ---
        # Student dots
        student_dots = ax_map.scatter([], [], s=45, zorder=3)
        
        # Buses markers
        bus_markers = []
        bus_texts = []
        for b in self.env.buses_data:
            m, = ax_map.plot([], [], marker='o', markersize=14, color=b["color"], markeredgecolor=TEXT_COLOR, markeredgewidth=1.5, zorder=5)
            bus_markers.append(m)
            t = ax_map.text(0, 0, "", color='#000000', fontsize=8, fontweight='bold', ha='center', va='center', zorder=6)
            bus_texts.append(t)
            
        # Rerouting/path indicators
        closure_lines = []
        
        # Dashboard elements
        dash_text = ax_dash.text(0.05, 0.95, "", color=TEXT_COLOR, fontsize=11, fontfamily='monospace', va='top')

        # --- 3. ANIMATION UPDATE FUNCTION ---
        def update_frame(frame_idx):
            state = self.history[frame_idx]
            
            # A. Update Student statuses
            s_lats, s_lngs, s_colors = [], [], []
            # status colors: waiting=blue, picked_up=hidden (drawn on bus), delivered=green, absent=gray, stranded=orange, late=red
            student_color_map = {
                "waiting": "#3b82f6",     # Blue
                "picked_up": "#fbbf24",   # Gold (hidden, but just in case)
                "delivered": "#22c55e",   # Green
                "absent": "#475569",      # Slate Gray
                "stranded": "#f97316",    # Orange (Rescue needed!)
                "late": "#ef4444"         # Red
            }
            
            for s in state["students"]:
                # If picked up, we don't draw them on the map (they are inside the bus!)
                if s["status"] == "picked_up":
                    continue
                s_lats.append(s["lat"])
                s_lngs.append(s["lng"])
                s_colors.append(student_color_map.get(s["status"], "#94a3b8"))
                
            if len(s_lats) > 0:
                student_dots.set_offsets(np.c_[s_lngs, s_lats])
                student_dots.set_color(s_colors)
            else:
                student_dots.set_offsets(np.empty((0, 2)))

            # B. Update Buses position, occupancy and status
            for idx, bus_state in enumerate(state["buses"]):
                m = bus_markers[idx]
                t = bus_texts[idx]
                
                # Position
                m.set_data([bus_state["lng"]], [bus_state["lat"]])
                t.set_position((bus_state["lng"], bus_state["lat"]))
                
                # Show occupancy number inside bus marker
                t.set_text(str(len(bus_state["passengers"])))
                
                # Check status
                if bus_state["status"] == "broken":
                    m.set_marker('X')
                    m.set_markersize(16)
                    m.set_color('#dc2626') # Vivid red for breakdown
                    t.set_text("")
                elif bus_state["status"] == "at_depot":
                    m.set_marker('h') # hexagon
                    m.set_markersize(12)
                    m.set_color('#64748b') # Grey
                    t.set_text("")
                else:
                    m.set_marker('o')
                    m.set_markersize(15)
                    m.set_color(self.env.buses_data[idx]["color"])

            # C. Draw active road closures as thick red segments
            # Clear old closure lines
            nonlocal closure_lines
            for line in closure_lines:
                line.remove()
            closure_lines = []
            
            for closure in state["active_road_closures"]:
                n_from = self.nodes[closure["from"]]
                n_to = self.nodes[closure["to"]]
                l, = ax_map.plot(
                    [n_from["lng"], n_to["lng"]], 
                    [n_from["lat"], n_to["lat"]], 
                    color='#ef4444', 
                    linewidth=3.5, 
                    linestyle='-',
                    zorder=2
                )
                closure_lines.append(l)

            # D. Highlight traffic spike edges
            traffic_mult = state["traffic_multiplier"]
            for edge in self.edges:
                u, v = edge["from"], edge["to"]
                line = edge_plots[(u, v)]
                if edge["street_type"] == "arterial" and traffic_mult > 1.2:
                    # Rush hour peak
                    line.set_color('#b91c1c') # Intense dark red
                    line.set_linewidth(2.2)
                else:
                    # Base conditions or local street
                    # Check if closed
                    is_closed = any(
                        (c["from"] == u and c["to"] == v) or (c["from"] == v and c["to"] == u)
                        for c in state["active_road_closures"]
                    )
                    if not is_closed:
                        line.set_color('#334155')
                        line.set_linewidth(1.2)

            # E. Update Dashboard Info
            t_formatted = self.env._format_time(state["time"])
            delivered = sum(1 for s in state["students"] if s["status"] in ["delivered", "late"])
            late = sum(1 for s in state["students"] if s["status"] == "late")
            absent = sum(1 for s in state["students"] if s["status"] == "absent")
            stranded = sum(1 for s in state["students"] if s["status"] == "stranded")
            waiting = sum(1 for s in state["students"] if s["status"] == "waiting")
            active_buses = sum(1 for b in state["buses"] if b["status"] not in ["broken", "at_depot"])
            
            # Format active events string
            events_str = ""
            if len(state["active_road_closures"]) > 0:
                events_str += f"⚠️ ROAD CLOSURES: {len(state['active_road_closures'])} active\n"
            if traffic_mult > 1.2:
                events_str += f"🚗 RUSH HOUR TRAFFIC: {traffic_mult:.1f}x delay\n"
            
            any_broken = any(b["status"] == "broken" for b in state["buses"])
            if any_broken:
                events_str += f"💥 VEHICLE BREAKDOWN: Bus stranded!\n"
                
            if events_str == "":
                events_str = "🟢 Normal operations\n"
                
            # Build pretty ASCII dashboard
            dash_content = (
                f"============ DISPATCH CENTER ============\n"
                f"  CURRENT CLOCK : {t_formatted}\n"
                f"  AGENT MODEL   : {self.agent.name}\n"
                f"=========================================\n\n"
                f"📋 STUDENT STATUS MATRIX:\n"
                f"  Delivered (On-Time) : {delivered - late:2d} \n"
                f"  Delivered (Late)    : {late:2d} ⚠️\n"
                f"  Waiting for Pickup  : {waiting:2d}\n"
                f"  Stranded (Stranded) : {stranded:2d} 🚨\n"
                f"  Absent / No-Show    : {absent:2d}\n\n"
                f"🚌 FLEET TELEMETRY:\n"
                f"  Active Service Buses: {active_buses:2d} / {self.env.num_buses}\n"
                f"  Total Distance      : {state['total_distance']:5.1f} miles\n\n"
                f"⚖️ EQUITY & QUALITY INDEX:\n"
                f"  Avg Ride Time       : {state['metrics']['avg_ride_time']:4.1f} mins\n"
                f"  Neighborhood Var    : {state['metrics']['ride_time_variance']:4.1f} mins^2\n\n"
                f"=========================================\n"
                f"📊 RUNNING VRP REWARD  : {state['reward']:7.1f} pts\n"
                f"=========================================\n\n"
                f"📢 DYNAMIC ALERTS:\n"
                f"{events_str}"
            )
            dash_text.set_text(dash_content)

        # Run animation
        anim = FuncAnimation(
            fig, 
            update_frame, 
            frames=len(self.history), 
            interval=100, # 100ms per frame = 5 seconds to play complete episode
            repeat=False
        )
        
        plt.tight_layout()
        plt.show()

def main():
    parser = argparse.ArgumentParser(description="SBRP Simulation Visualizer - Hackensack, NJ")
    parser.add_argument(
        "--agent", 
        choices=["random", "nn", "static", "dqn"], 
        default="nn",
        help="Agent model to evaluate: random, nn (Nearest Neighbor), static (OR-Tools VRP Static), or dqn (Trained RL)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for simulation reset")
    args = parser.parse_args()

    vis = SimulationVisualizer(agent_type=args.agent, seed=args.seed)
    vis.start_animation()

if __name__ == "__main__":
    main()
