import os
import json
import torch
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS

from sbrp_env import SchoolBusRoutingEnv
from train import DQNAgent

app = Flask(__name__)
CORS(app) # Allow JS frontend to call this API

print("Initializing Environment and DQN Agent...")
env = SchoolBusRoutingEnv()

# Ensure we're in the right directory
dir_path = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(dir_path, "models", "dqn_dispatcher.pth")

# Get dims from a dummy state
obs_dict, _ = env.reset(seed=42)
flat_obs = env.get_flat_observation(obs_dict)
state_dim = flat_obs.shape[0]
action_dim = env.num_actions

agent = DQNAgent(state_dim, action_dim)
if os.path.exists(model_path):
    agent.load(model_path)
    agent.policy_net.eval()
    print(f"Loaded trained DQN from {model_path}")
else:
    print(f"WARNING: Model not found at {model_path}. Agent will act randomly!")

def sync_env_state(js_state):
    """Update Python env to match JS simulation state exactly"""
    env.current_time = js_state["time"]
    
    # Identify active bus
    active_bus_id = js_state["active_bus_id"]
    active_idx = -1
    
    # Sync Buses
    for i, b_js in enumerate(js_state["buses"]):
        b_py = env.buses[i]
        b_py["lat"] = b_js["lat"]
        b_py["lng"] = b_js["lng"]
        b_py["passengers"] = b_js["passengers"]
        b_py["node"] = b_js["node"]
        
        if b_js["status"] == "en route":
            b_py["status"] = "moving"
        else:
            b_py["status"] = b_js["status"]
            
        b_py["time_remaining"] = b_js.get("time_remaining", 0.0)
        b_py["destination"] = b_js.get("destination", b_js["node"])
        
        if b_js["id"] == active_bus_id:
            active_idx = i

    env.active_bus_idx = active_idx
    
    # Sync Students
    # Map by ID since JS order might theoretically differ, though unlikely
    student_map = {s["id"]: s for s in js_state["students"]}
    for s_py in env.students:
        s_js = student_map.get(s_py["id"])
        if s_js:
            s_py["lat"] = s_js["lat"]
            s_py["lng"] = s_js["lng"]
            # Convert picked-up to picked_up
            s_py["status"] = s_js["status"].replace("-", "_")
            
    # Sync Network Disruptions
    js_net = js_state.get("network", {})
    traffic_map = js_net.get("trafficMultipliers", {})
    closed_list = js_net.get("closedEdges", [])
    
    # Reset network weights to base
    for u, v, d in env.G.edges(data=True):
        d["weight"] = d["base_travel_time"]
        d["traffic_multiplier"] = 1.0

    env.active_road_closures = []
    
    # Apply closures
    for edge_str in closed_list:
        parts = edge_str.split("-")
        if len(parts) == 2:
            u, v = parts
            env.active_road_closures.append({"from": u, "to": v})
            if env.G.has_edge(u, v): env.G[u][v]["weight"] = 1e6
            if env.G.has_edge(v, u): env.G[v][u]["weight"] = 1e6

    # Apply traffic
    for edge_str, mult in traffic_map.items():
        parts = edge_str.split("-")
        if len(parts) == 2:
            u, v = parts
            if env.G.has_edge(u, v) and env.G[u][v]["weight"] < 1e5:
                env.G[u][v]["traffic_multiplier"] = mult
                env.G[u][v]["weight"] = env.G[u][v]["base_travel_time"] * mult
            if env.G.has_edge(v, u) and env.G[v][u]["weight"] < 1e5:
                env.G[v][u]["traffic_multiplier"] = mult
                env.G[v][u]["weight"] = env.G[v][u]["base_travel_time"] * mult


@app.route('/decide', methods=['POST'])
def decide():
    try:
        js_state = request.json
        
        # 1. Sync Python env with JS state
        sync_env_state(js_state)
        
        # 2. Get observation & mask natively
        obs_dict = env._get_obs()
        flat_obs = env.get_flat_observation(obs_dict)
        action_mask = obs_dict["action_mask"]
        
        # 3. Forward pass
        state_t = torch.FloatTensor(flat_obs).unsqueeze(0).to(agent.device)
        with torch.no_grad():
            q_values = agent.policy_net(state_t).cpu().numpy()[0]
            
        # 4. Mask invalid actions
        q_values[action_mask == 0.0] = -1e9
        action = int(np.argmax(q_values))
        
        # 5. Translate action index back to target node & semantic action
        target_node = None
        target_student_id = None
        semantic_action = "wait"
        
        if action < env.num_students:
            semantic_action = "pickup"
            s = env.students[action]
            target_node = s["home_node"]
            target_student_id = s["id"]
        elif action < env.num_students + env.num_schools:
            semantic_action = "dropoff"
            sch_idx = action - env.num_students
            sch_id = env.school_ids[sch_idx]
            target_node = env.schools_data[sch_id]["node"]
        elif action == env.num_students + env.num_schools:
            semantic_action = "return"
            target_node = env.depots_data["depot_1"]["node"]
            
        print(f"Decided: {semantic_action} -> {target_node} (Action ID: {action})")
            
        return jsonify({
            "action": semantic_action,
            "targetNode": target_node,
            "targetStudentId": target_student_id,
            "rawActionIndex": action
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Run the server on port 5000
    app.run(host='127.0.0.1', port=5000)
