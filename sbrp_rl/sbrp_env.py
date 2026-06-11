import os
import json
import random
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import networkx as nx

class SchoolBusRoutingEnv(gym.Env):
    """
    A high-fidelity Gymnasium environment for the School Bus Routing Problem (SBRP) in Hackensack, NJ.
    This environment is designed as a machine learning competition where static scheduling is made 
    extremely difficult due to dynamic, online disruptions, staggered school times, information asymmetry,
    and highly non-linear neighborhood equity objectives.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self, scenario_path=None, max_steps=1000):
        super().__init__()
        
        # Load scenario
        if scenario_path is None:
            # Look for hackensack_network.json in the same directory as this file
            dir_path = os.path.dirname(os.path.abspath(__file__))
            scenario_path = os.path.join(dir_path, "hackensack_network.json")
            
        with open(scenario_path, "r") as f:
            self.scenario_data = json.load(f)
            
        self.max_steps = max_steps
        
        # Extract network
        self.nodes_data = self.scenario_data["nodes"]
        self.edges_data = self.scenario_data["edges"]
        
        # Extract schools, depots, students, and buses
        self.schools_data = self.scenario_data["schools"]
        self.depots_data = self.scenario_data["depots"]
        self.students_data = self.scenario_data["students"]
        self.buses_data = self.scenario_data["buses"]
        
        self.num_students = len(self.students_data)
        self.num_schools = len(self.schools_data)
        self.num_buses = len(self.buses_data)
        self.num_depots = len(self.depots_data)
        
        # Mapping helpers
        self.student_ids = [s["id"] for s in self.students_data]
        self.school_ids = list(self.schools_data.keys())
        self.bus_ids = [b["id"] for b in self.buses_data]
        
        self.student_id_to_idx = {sid: idx for idx, sid in enumerate(self.student_ids)}
        self.school_id_to_idx = {sch_id: idx for idx, sch_id in enumerate(self.school_ids)}
        self.bus_id_to_idx = {bid: idx for idx, bid in enumerate(self.bus_ids)}

        # Geographic bounds
        self.lat_bounds = self.scenario_data["meta"]["lat_bounds"]
        self.lng_bounds = self.scenario_data["meta"]["lng_bounds"]

        # Action Space: central dispatcher assigns a destination for the active bus
        # Choice of action:
        # 0 to num_students-1: Go to student's home node (pickup)
        # num_students to num_students+num_schools-1: Go to school (dropoff)
        # num_students+num_schools: Go to depot (finish day)
        # num_students+num_schools+1: Wait for 5 minutes
        self.num_actions = self.num_students + self.num_schools + 2
        self.action_space = spaces.Discrete(self.num_actions)
        
        # Observation Space (Dict representation, which we'll also flatten)
        # We define a structured Dict space
        self.observation_space = spaces.Dict({
            "time": spaces.Box(low=420.0, high=570.0, shape=(1,), dtype=np.float32),
            "active_bus_idx": spaces.Discrete(self.num_buses + 1, start=-1), # -1 to num_buses-1
            "bus_states": spaces.Box(low=0.0, high=1.0, shape=(self.num_buses, 5), dtype=np.float32), 
            # bus_states columns: [lat, lng, occupancy_pct, status_code, time_remaining]
            # status_code: 0=idle, 1=moving, 2=broken, 3=at_depot
            "student_states": spaces.Box(low=0.0, high=1.0, shape=(self.num_students, 6), dtype=np.float32),
            # student_states columns: [lat, lng, school_idx, status_code, pickup_start, pickup_end]
            # status_code: 0=waiting, 1=picked_up, 2=delivered, 3=absent/no-show, 4=stranded, 5=late
            "disruptions": spaces.Box(low=0.0, high=10.0, shape=(len(self.edges_data) // 2,), dtype=np.float32),
            # traffic multipliers for the key bidirectional road segments
            "action_mask": spaces.Box(low=0.0, high=1.0, shape=(self.num_actions,), dtype=np.float32)
        })
        
        # Initialize road network graph
        self._build_graph()

    def _build_graph(self):
        self.G = nx.DiGraph()
        for nid, ninfo in self.nodes_data.items():
            self.G.add_node(nid, lat=ninfo["lat"], lng=ninfo["lng"], neighborhood=ninfo["neighborhood"])
        
        self.edge_index_to_nodes = {}
        self.edge_nodes_to_index = {}
        
        # Keep track of unique bidirectional edges for disruption observation
        bi_edges_added = set()
        self.bi_edge_list = []

        for idx, edge in enumerate(self.edges_data):
            self.G.add_edge(
                edge["from"], 
                edge["to"], 
                weight=edge["travel_time_mins"],
                base_weight=edge["travel_time_mins"],
                distance=edge["distance_miles"],
                speed=edge["speed_mph"],
                street_type=edge["street_type"],
                closed=False,
                traffic_multiplier=1.0
            )
            
            # Group into bidirectional segments for visualization / observation
            u, v = edge["from"], edge["to"]
            seg_key = tuple(sorted([u, v]))
            if seg_key not in bi_edges_added:
                bi_edges_added.add(seg_key)
                self.bi_edge_list.append(seg_key)
                
            self.edge_index_to_nodes[idx] = (u, v)
            self.edge_nodes_to_index[(u, v)] = idx

    def get_action_mask(self, bus_idx):
        """
        Returns a binary array of size num_actions representing valid destinations.
        A destination is valid if:
        - Student home: Student is 'waiting' or 'stranded', and not assigned to another bus, and bus has capacity.
        - School: Bus is carrying at least one student assigned to that school.
        - Depot: Bus is empty, has picked up everyone it needs to, or has run out of time.
        - Wait: Always valid.
        """
        mask = np.zeros(self.num_actions, dtype=np.float32)
        
        if bus_idx < 0 or bus_idx >= self.num_buses:
            mask[-1] = 1.0 # Wait action is default
            return mask
            
        bus = self.buses[bus_idx]
        
        # If the bus is broken or finished, it has no valid actions except waiting/do-nothing
        if bus["status"] in ["broken", "at_depot"]:
            mask[-1] = 1.0
            return mask

        # 1. Student pickup actions (0 to num_students-1)
        for s_idx, student in enumerate(self.students):
            # Check capacity
            has_capacity = len(bus["passengers"]) < bus["capacity"]
            
            # Check if student needs pickup (waiting or stranded) and is not already targeted by another active bus
            is_available = student["status"] in ["waiting", "stranded"]
            
            # Check if targeted by another bus
            is_targeted = False
            for b_idx, b in enumerate(self.buses):
                if b_idx != bus_idx and b["destination"] == student["home_node"]:
                    is_targeted = True
                    break
            
            if has_capacity and is_available and not is_targeted:
                mask[s_idx] = 1.0

        # 2. School dropoff actions (num_students to num_students+num_schools-1)
        for sch_idx, school_id in enumerate(self.school_ids):
            # Valid to visit if the bus has passengers assigned to this school
            has_student_for_school = any(
                self.students[self.student_id_to_idx[sid]]["school_id"] == school_id 
                for sid in bus["passengers"]
            )
            if has_student_for_school:
                mask[self.num_students + sch_idx] = 1.0

        # 3. Depot action (num_students+num_schools)
        # Valid to return to depot if bus is empty
        if len(bus["passengers"]) == 0:
            mask[self.num_students + self.num_schools] = 1.0
            
        # 4. Wait action (num_students+num_schools+1)
        mask[-1] = 1.0
        
        # If no other actions are possible, returning to depot or waiting is always valid
        if np.sum(mask[:-2]) == 0:
            mask[self.num_students + self.num_schools] = 1.0
            
        return mask

    def get_flat_observation(self, dict_obs):
        """Converts the Dict observation into a flat 1D numpy array."""
        flat_obs = []
        flat_obs.append(dict_obs["time"])
        flat_obs.append([float(dict_obs["active_bus_idx"])])
        flat_obs.append(dict_obs["bus_states"].flatten())
        flat_obs.append(dict_obs["student_states"].flatten())
        flat_obs.append(dict_obs["disruptions"].flatten())
        flat_obs.append(dict_obs["action_mask"].flatten())
        
        # Add travel times from active bus to all potential targets (34 features)
        active_bus_idx = int(dict_obs["active_bus_idx"])
        travel_times = np.zeros(self.num_students + self.num_schools + 1, dtype=np.float32)
        
        if active_bus_idx >= 0 and active_bus_idx < self.num_buses:
            bus = self.buses[active_bus_idx]
            bus_node = bus["node"]
            
            # 1. To student home nodes (indices 0 to 29)
            for s_idx, student in enumerate(self.students):
                try:
                    dist = nx.dijkstra_path_length(self.G, bus_node, student["home_node"], weight="weight")
                    travel_times[s_idx] = dist / 60.0 # normalized by 60 mins
                except nx.NetworkXNoPath:
                    travel_times[s_idx] = 1.0 # default high value
                    
            # 2. To schools (indices 30 to 32)
            for sch_idx, school_id in enumerate(self.school_ids):
                school_node = self.schools_data[school_id]["node"]
                try:
                    dist = nx.dijkstra_path_length(self.G, bus_node, school_node, weight="weight")
                    travel_times[self.num_students + sch_idx] = dist / 60.0
                except nx.NetworkXNoPath:
                    travel_times[self.num_students + sch_idx] = 1.0
                    
            # 3. To depot (index 33)
            depot_node = self.depots_data["depot_1"]["node"]
            try:
                dist = nx.dijkstra_path_length(self.G, bus_node, depot_node, weight="weight")
                travel_times[self.num_students + self.num_schools] = dist / 60.0
            except nx.NetworkXNoPath:
                travel_times[self.num_students + self.num_schools] = 1.0
                
        flat_obs.append(travel_times)
        return np.concatenate(flat_obs).astype(np.float32)

    def _get_obs(self):
        # 1. Normalized Time [0, 1]
        norm_time = (self.current_time - 420.0) / 150.0
        
        # 2. Active Bus Index
        active_bus = self.active_bus_idx
        
        # 3. Bus States (num_buses, 5)
        bus_states = np.zeros((self.num_buses, 5), dtype=np.float32)
        for i, b in enumerate(self.buses):
            # Normalize lat/lng
            lat_norm = (b["lat"] - self.lat_bounds[0]) / (self.lat_bounds[1] - self.lat_bounds[0])
            lng_norm = (b["lng"] - self.lng_bounds[0]) / (self.lng_bounds[1] - self.lng_bounds[0])
            occupancy_pct = len(b["passengers"]) / b["capacity"]
            
            status_map = {"idle": 0.0, "moving": 0.33, "broken": 0.66, "at_depot": 1.0}
            status_code = status_map.get(b["status"], 0.0)
            
            time_rem = b["time_remaining"] / 60.0 # Normalized by 60 mins max
            
            bus_states[i] = [lat_norm, lng_norm, occupancy_pct, status_code, time_rem]
            
        # 4. Student States (num_students, 6)
        student_states = np.zeros((self.num_students, 6), dtype=np.float32)
        for i, s in enumerate(self.students):
            lat_norm = (s["lat"] - self.lat_bounds[0]) / (self.lat_bounds[1] - self.lat_bounds[0])
            lng_norm = (s["lng"] - self.lng_bounds[0]) / (self.lng_bounds[1] - self.lng_bounds[0])
            
            sch_idx = self.school_id_to_idx[s["school_id"]] / float(self.num_schools - 1)
            
            status_map = {"waiting": 0.0, "picked_up": 0.2, "delivered": 0.4, "absent": 0.6, "stranded": 0.8, "late": 1.0}
            status_code = status_map.get(s["status"], 0.0)
            
            w_start = (s["pickup_window"][0] - 420.0) / 150.0
            w_end = (s["pickup_window"][1] - 420.0) / 150.0
            
            student_states[i] = [lat_norm, lng_norm, sch_idx, status_code, w_start, w_end]
            
        # 5. Disruptions (num_bi_segments,)
        disruptions = np.zeros(len(self.bi_edge_list), dtype=np.float32)
        for idx, (u, v) in enumerate(self.bi_edge_list):
            # Check edge attributes
            edge_data = self.G.get_edge_data(u, v)
            if edge_data is None:
                mult = 1.0
            elif edge_data.get("closed", False):
                mult = 10.0 # Representation for closed
            else:
                mult = edge_data.get("traffic_multiplier", 1.0)
            disruptions[idx] = (mult - 1.0) / 9.0 # Normalized [0, 1]

        # 6. Action Mask
        action_mask = self.get_action_mask(self.active_bus_idx)

        dict_obs = {
            "time": np.array([norm_time], dtype=np.float32),
            "active_bus_idx": self.active_bus_idx,
            "bus_states": bus_states,
            "student_states": student_states,
            "disruptions": disruptions,
            "action_mask": action_mask
        }
        
        return dict_obs

    def _get_info(self):
        delivered = sum(1 for s in self.students if s["status"] in ["delivered", "late"] and s["delivery_time"] is not None)
        late = sum(1 for s in self.students if s["status"] == "late")
        absent = sum(1 for s in self.students if s["status"] == "absent")
        stranded = sum(1 for s in self.students if s["status"] == "stranded")
        waiting = sum(1 for s in self.students if s["status"] == "waiting")
        active_buses = sum(1 for b in self.buses if b["status"] != "broken" and b["status"] != "at_depot")
        
        metrics = self._calculate_metrics()
        
        return {
            "time_formatted": self._format_time(self.current_time),
            "delivered_count": delivered,
            "late_count": late,
            "absent_count": absent,
            "stranded_count": stranded,
            "waiting_count": waiting,
            "active_buses": active_buses,
            "avg_ride_time": metrics["avg_ride_time"],
            "equity_variance": metrics["ride_time_variance"],
            "total_distance": self.total_distance,
            "active_bus_idx": self.active_bus_idx
        }

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
            
        self.current_time = 420.0  # 7:00 AM in minutes
        self.end_time = 570.0  # 9:30 AM
        self.total_distance = 0.0
        self.step_count = 0
        self.active_bus_idx = -1
        
        # Stochastically choose weather multiplier
        weather_roll = random.random()
        if weather_roll < 0.60:
            self.weather_multiplier = 1.0  # Clear
        elif weather_roll < 0.90:
            self.weather_multiplier = 1.25 # Rain
        else:
            self.weather_multiplier = 1.50 # Snow
            
        self.active_road_closures = []
        self.active_traffic_spikes = []
        self.state_history = []  # To record detailed tick-by-tick snapshots for visualization
        
        # Reset the road network to base state and apply weather/initial traffic
        self._build_graph()
        
        # Reset Students with stochastic attendance and no-shows
        self.students = []
        for s in self.students_data:
            node_info = self.nodes_data[s["home_node"]]
            
            # Stochastic absence decided at the start
            is_present = random.random() < s["attendance_prob"]
            # To model "no-shows" (unknown until bus arrival):
            # 30% of absent students' status is pre-notified (known as 'absent' at t=420)
            # 70% are no-shows (initially appear 'waiting', but turn 'absent' only upon bus arrival)
            pre_notified = False
            if not is_present and random.random() < 0.3:
                pre_notified = True
                
            self.students.append({
                "id": s["id"],
                "home_node": s["home_node"],
                "lat": node_info["lat"],
                "lng": node_info["lng"],
                "school_id": s["school_id"],
                "pickup_window": s["pickup_window"],
                "neighborhood": s["neighborhood"],
                "special_needs": s["special_needs"],
                "status": "absent" if pre_notified else "waiting",
                "pickup_time": None,
                "delivery_time": None,
                "ride_time": 0.0,
                "bus_id": None,
                "is_present": is_present, # Hidden ground truth
                "original_status": s["special_needs"]
            })

        # Reset Buses
        self.buses = []
        depot_node = self.depots_data["depot_1"]["node"]
        depot_info = self.nodes_data[depot_node]
        for b in self.buses_data:
            self.buses.append({
                "id": b["id"],
                "capacity": b["capacity"],
                "color": b["color"],
                "node": depot_node,
                "lat": depot_info["lat"],
                "lng": depot_info["lng"],
                "status": "idle", # idle, moving, broken, at_depot
                "passengers": [], # student IDs on board
                "path": [], # nodes list
                "time_remaining": 0.0, # minutes remaining to complete path
                "destination": None, # node ID
                "route_distance": 0.0
            })

        # Pre-schedule road closures and traffic spikes to happen dynamically
        self.scheduled_closures = []
        # Stochastically schedule 2-3 road closures (more complex)
        num_closures = random.randint(2, 3)
        candidate_edges = [e for e in self.edges_data if e["street_type"] == "arterial"]
        for _ in range(num_closures):
            edge = random.choice(candidate_edges)
            close_time = float(random.randint(440, 500)) # Between 7:20 and 8:20 AM
            duration = float(random.randint(30, 60)) # Longer duration (30-60 mins)
            self.scheduled_closures.append({
                "time": close_time,
                "duration": duration,
                "from": edge["from"],
                "to": edge["to"],
                "desc": f"Accident blocking {edge['from']} to {edge['to']}",
                "triggered": False,
                "expired": False
            })

        # Pre-schedule traffic spike (7:30 to 8:30 AM is peak rush hour)
        self.scheduled_traffic = {
            "start_time": 450.0, # 7:30 AM
            "peak_time": 480.0,  # 8:00 AM
            "end_time": 510.0,   # 8:30 AM
            "max_multiplier": 2.5, # Increased traffic congestion multiplier (2.5x)
            "active": False
        }

        # Schedule bus breakdown (5% chance of breakdown during episode)
        self.breakdown_bus_id = None
        if random.random() < 0.35: # Make it 35% chance in the competition to force students to implement rescue!
            self.breakdown_bus_id = f"bus_{random.randint(1, self.num_buses)}"
            self.breakdown_time = float(random.randint(450, 490)) # Breaks down between 7:30 and 8:10 AM
            self.breakdown_triggered = False

        # Apply initial weather/traffic updates now that all scheduling data is initialized
        self._update_traffic()

        # Find initial active bus
        self._update_active_bus()
        
        # If no bus is active (which shouldn't be the case at start since all are idle), advance time
        if self.active_bus_idx == -1:
            self._advance_time()

        return self._get_obs(), self._get_info()

    def _update_active_bus(self):
        """Finds the first bus that is currently idle and needs a decision. Sets active_bus_idx."""
        # Find any bus that is status 'idle' and has empty path
        for i, b in enumerate(self.buses):
            if b["status"] == "idle" and len(b["path"]) == 0:
                self.active_bus_idx = i
                return
        self.active_bus_idx = -1

    def step(self, action):
        self.step_count += 1
        bus_idx = self.active_bus_idx
        
        # If no active bus or invalid action chosen
        if bus_idx == -1:
            # Re-evaluate active bus and advance
            self._update_active_bus()
            if self.active_bus_idx == -1:
                self._advance_time()
            obs = self._get_obs()
            info = self._get_info()
            terminated = self._check_terminated()
            return obs, 0.0, terminated, False, info

        bus = self.buses[bus_idx]
        action_mask = self.get_action_mask(bus_idx)
        
        # Invalid Action handling
        if action_mask[action] == 0.0:
            # Heavy penalty for invalid action
            reward = -100.0
            # Force a wait action instead to avoid getting stuck
            action = self.num_actions - 1 
        else:
            reward = 0.0

        # Translate Action to target node
        target_node = None
        target_student_id = None
        
        if action < self.num_students:
            # Action is student pickup
            target_student_id = self.student_ids[action]
            target_node = self.students[action]["home_node"]
        elif action < self.num_students + self.num_schools:
            # Action is school dropoff
            sch_idx = action - self.num_students
            target_node = self.schools_data[self.school_ids[sch_idx]]["node"]
        elif action == self.num_students + self.num_schools:
            # Action is return to depot
            target_node = self.depots_data["depot_1"]["node"]
        else:
            # Action is Wait (5 minutes)
            target_node = bus["node"] # Wait at current node
            
        # Assign path to bus
        if action == self.num_actions - 1:
            # Wait action
            bus["status"] = "moving"
            bus["path"] = [bus["node"], bus["node"]] # Staying in place
            bus["time_remaining"] = 5.0
            bus["destination"] = bus["node"]
            bus["route_distance"] = 0.0
        else:
            # Compute shortest path via NetworkX
            if bus["node"] == target_node:
                bus["status"] = "moving"
                bus["path"] = [bus["node"], bus["node"]]
                bus["time_remaining"] = 5.0
                bus["destination"] = bus["node"]
                bus["route_distance"] = 0.0
            else:
                try:
                    path = nx.dijkstra_path(self.G, bus["node"], target_node, weight="weight")
                    path_time = nx.dijkstra_path_length(self.G, bus["node"], target_node, weight="weight")
                    
                    # Compute distance
                    path_dist = 0.0
                    for u, v in zip(path[:-1], path[1:]):
                        path_dist += self.G[u][v]["distance"]
                    
                    bus["status"] = "moving"
                    bus["path"] = path
                    bus["time_remaining"] = path_time
                    bus["destination"] = target_node
                    bus["route_distance"] = path_dist
                except nx.NetworkXNoPath:
                    # Fallback if no path (e.g. extreme road closures isolated a node)
                    # Force wait
                    bus["status"] = "moving"
                    bus["path"] = [bus["node"], bus["node"]]
                    bus["time_remaining"] = 5.0
                    bus["destination"] = bus["node"]
                    bus["route_distance"] = 0.0
                    reward -= 10.0 # Reroute failure penalty

        # If a student is picked up, we associate them with the bus route target
        # (This is cleared upon arrival)
        
        # Advance the environment time and simulate bus movements
        self.active_bus_idx = -1 # Clear active bus since it's now moving
        self._advance_time()
        
        # Calculate step reward
        reward += self._calculate_step_reward()
        
        # Check termination
        terminated = self._check_terminated()
        truncated = self.step_count >= self.max_steps
        
        # Get next active bus
        self._update_active_bus()
        if not terminated and not truncated and self.active_bus_idx == -1:
            # Loop until a bus needs an action or episode ends
            self._advance_time()
            self._update_active_bus()
            
        obs = self._get_obs()
        info = self._get_info()
        
        return obs, reward, terminated, truncated, info

    def _advance_time(self):
        """Advances the simulation in tiny steps until a bus is idle or the end time is reached."""
        time_step = 0.5 # 30 seconds increments
        
        while self.current_time < self.end_time:
            # 1. Update dynamic disruptions
            self._update_traffic()
            self._update_closures()
            self._update_breakdown()
            
            # 2. Move buses
            buses_need_decision = False
            
            for idx, bus in enumerate(self.buses):
                if bus["status"] == "moving":
                    # Reduce remaining travel time
                    bus["time_remaining"] -= time_step
                    
                    # Accumulate distance driven
                    # We distribute distance proportionally over travel time
                    if bus["time_remaining"] > 0:
                        dist_moved = (time_step / (bus["time_remaining"] + time_step)) * bus["route_distance"]
                        self.total_distance += dist_moved
                        bus["route_distance"] -= dist_moved
                    else:
                        self.total_distance += bus["route_distance"]
                        bus["route_distance"] = 0.0

                    # Handle actual movement along nodes
                    # We estimate current position along path
                    if bus["time_remaining"] <= 0:
                        # Bus has arrived!
                        bus["node"] = bus["destination"]
                        node_info = self.nodes_data[bus["node"]]
                        bus["lat"] = node_info["lat"]
                        bus["lng"] = node_info["lng"]
                        bus["path"] = []
                        bus["time_remaining"] = 0.0
                        bus["status"] = "idle"
                        
                        # Handle arrival logic (pickup/dropoff)
                        self._handle_bus_arrival(idx)
                        
                        if bus["status"] == "idle":
                            buses_need_decision = True
                    else:
                        # Estimate intermediate coordinates
                        # Place bus at an approximate location between path nodes
                        path = bus["path"]
                        if len(path) > 1:
                            # Estimate fraction of completion
                            # We can simplify: just interpolate between current node and destination
                            curr_node = path[0]
                            dest_node = bus["destination"]
                            c_info = self.nodes_data[curr_node]
                            d_info = self.nodes_data[dest_node]
                            
                            # Just simple linear interpolation for visual realism
                            total_est_time = nx.dijkstra_path_length(self.G, curr_node, dest_node, weight="weight")
                            if total_est_time > 0:
                                frac = max(0.0, min(1.0, 1.0 - (bus["time_remaining"] / total_est_time)))
                                bus["lat"] = c_info["lat"] + frac * (d_info["lat"] - c_info["lat"])
                                bus["lng"] = c_info["lng"] + frac * (d_info["lng"] - c_info["lng"])

            # Increment time
            self.current_time += time_step
            
            # Record tick history for animation
            self.state_history.append({
                "time": self.current_time,
                "buses": [
                    {
                        "id": b["id"],
                        "lat": b["lat"],
                        "lng": b["lng"],
                        "status": b["status"],
                        "passengers": list(b["passengers"]),
                        "destination": b["destination"]
                    } for b in self.buses
                ],
                "students": [
                    {
                        "id": s["id"],
                        "lat": s["lat"],
                        "lng": s["lng"],
                        "status": s["status"],
                        "home_node": s["home_node"]
                    } for s in self.students
                ],
                "active_road_closures": [
                    {"from": c["from"], "to": c["to"]} for c in self.active_road_closures
                ],
                "traffic_multiplier": self.G[self.edges_data[0]["from"]][self.edges_data[0]["to"]].get("traffic_multiplier", 1.0) if len(self.edges_data) > 0 else 1.0,
                "metrics": self._calculate_metrics(),
                "total_distance": self.total_distance,
                "reward": self.compute_final_reward()
            })
            
            # If a bus has arrived and needs a decision, pause time advancement
            if buses_need_decision:
                break
                
            # If all buses are at depot or broken, and all students delivered, we can terminate early
            if self._check_early_termination():
                break

    def _handle_bus_arrival(self, bus_idx):
        bus = self.buses[bus_idx]
        arrival_node = bus["node"]
        
        # 1. Check if we arrived at a student node for pickup
        # (Could be multiple students living at the same intersection, or stranded students!)
        students_at_node = [
            s for s in self.students 
            if s["home_node"] == arrival_node and s["status"] in ["waiting", "stranded"]
        ]
        
        for student in students_at_node:
            # Check capacity
            if len(bus["passengers"]) < bus["capacity"]:
                # If they are stranded, they are immediately picked up (rescue mechanic!)
                if student["status"] == "stranded":
                    student["status"] = "picked_up"
                    student["bus_id"] = bus["id"]
                    bus["passengers"].append(student["id"])
                else:
                    # Stochastically check attendance (information asymmetry: revealed only upon arrival)
                    if student["is_present"]:
                        student["status"] = "picked_up"
                        student["pickup_time"] = self.current_time
                        student["bus_id"] = bus["id"]
                        bus["passengers"].append(student["id"])
                    else:
                        # Student is absent (no-show)
                        student["status"] = "absent"
                        # Waste 1 minute of bus time for waiting!
                        bus["status"] = "moving"
                        bus["time_remaining"] = 1.0
                        bus["path"] = [arrival_node, arrival_node]
                        bus["destination"] = arrival_node
            
        # 2. Check if we arrived at a school node for dropoff
        for sch_id, sch_info in self.schools_data.items():
            if sch_info["node"] == arrival_node:
                # Drop off students whose assigned school is this school
                dropped_off_ids = []
                for sid in bus["passengers"]:
                    student = self.students[self.student_id_to_idx[sid]]
                    if student["school_id"] == sch_id:
                        student["delivery_time"] = self.current_time
                        student["ride_time"] = student["delivery_time"] - student["pickup_time"]
                        
                        # Check if delivered on-time or late
                        # Staggered bell times: HHS=480, HMS=510, FES=540
                        if self.current_time <= sch_info["bell_time"]:
                            student["status"] = "delivered"
                        else:
                            student["status"] = "late"
                        dropped_off_ids.append(sid)
                
                # Remove from bus passengers
                bus["passengers"] = [sid for sid in bus["passengers"] if sid not in dropped_off_ids]
                
        # 3. Check if we arrived at depot
        depot_node = self.depots_data["depot_1"]["node"]
        if arrival_node == depot_node and len(bus["passengers"]) == 0:
            # If all students are picked up or time is late, bus finishes day
            all_done = all(s["status"] not in ["waiting", "stranded"] for s in self.students)
            if all_done or self.current_time > 510.0: # After 8:30 AM, buses return to finish
                bus["status"] = "at_depot"

    def _update_traffic(self):
        """Applies rush-hour traffic multipliers stochastically based on peak period 7:30 - 8:30 AM."""
        st = self.scheduled_traffic
        curr = self.current_time
        
        if st["start_time"] <= curr <= st["end_time"]:
            # Calculate bell-shaped multiplier peaking at 8:00 AM (480 mins)
            # max multiplier is 2.2x
            diff = abs(curr - st["peak_time"])
            span = (st["end_time"] - st["start_time"]) / 2.0
            mult = 1.0 + (st["max_multiplier"] - 1.0) * max(0.0, 1.0 - (diff / span))
            
            # Apply to arterial edges in NetworkX
            for u, v, d in self.G.edges(data=True):
                if d["street_type"] == "arterial":
                    d["traffic_multiplier"] = mult
                    d["weight"] = d["base_weight"] * mult * self.weather_multiplier
        else:
            # Reset traffic to base
            for u, v, d in self.G.edges(data=True):
                d["traffic_multiplier"] = 1.0
                d["weight"] = d["base_weight"] * self.weather_multiplier

    def _update_closures(self):
        """Triggers and expires road closures, causing buses to dynamically reroute."""
        curr = self.current_time
        
        for closure in self.scheduled_closures:
            # Trigger closure
            if curr >= closure["time"] and not closure["triggered"]:
                closure["triggered"] = True
                u, v = closure["from"], closure["to"]
                
                # Mark edge as closed
                if self.G.has_edge(u, v):
                    self.G[u][v]["closed"] = True
                    self.G[u][v]["weight"] = float("inf")
                if self.G.has_edge(v, u): # bidirectional
                    self.G[v][u]["closed"] = True
                    self.G[v][u]["weight"] = float("inf")
                
                self.active_road_closures.append(closure)
                
                # DYNAMIC REROUTING: Force any bus currently traveling along a path containing this edge to replan!
                for bus in self.buses:
                    if bus["status"] == "moving" and len(bus["path"]) > 1:
                        # Check if closed segment is in path
                        path = bus["path"]
                        has_closed_edge = False
                        for p_u, p_v in zip(path[:-1], path[1:]):
                            if (p_u == u and p_v == v) or (p_u == v and p_v == u):
                                has_closed_edge = True
                                break
                        
                        if has_closed_edge:
                            # Replan from current bus position!
                            try:
                                new_path = nx.dijkstra_path(self.G, bus["node"], bus["destination"], weight="weight")
                                new_time = nx.dijkstra_path_length(self.G, bus["node"], bus["destination"], weight="weight")
                                bus["path"] = new_path
                                bus["time_remaining"] = new_time
                            except nx.NetworkXNoPath:
                                # isolated, wait in place
                                bus["path"] = [bus["node"], bus["node"]]
                                bus["time_remaining"] = 5.0

            # Expire closure
            if curr >= (closure["time"] + closure["duration"]) and closure["triggered"] and not closure["expired"]:
                closure["expired"] = True
                u, v = closure["from"], closure["to"]
                
                # Reopen edge
                if self.G.has_edge(u, v):
                    self.G[u][v]["closed"] = False
                    self.G[u][v]["weight"] = self.G[u][v]["base_weight"] * self.G[u][v]["traffic_multiplier"] * self.weather_multiplier
                if self.G.has_edge(v, u):
                    self.G[v][u]["closed"] = False
                    self.G[v][u]["weight"] = self.G[v][u]["base_weight"] * self.G[v][u]["traffic_multiplier"] * self.weather_multiplier
                
                if closure in self.active_road_closures:
                    self.active_road_closures.remove(closure)

    def _update_breakdown(self):
        """Triggers a mechanical breakdown on a scheduled bus, stranding its passengers."""
        if self.breakdown_bus_id is None:
            return
            
        curr = self.current_time
        if curr >= self.breakdown_time and not self.breakdown_triggered:
            self.breakdown_triggered = True
            bus = self.buses[self.bus_id_to_idx[self.breakdown_bus_id]]
            
            # Bus breaks down!
            bus["status"] = "broken"
            bus["path"] = []
            bus["time_remaining"] = 0.0
            
            # Strand passengers at the bus's current location!
            stranded_passengers = list(bus["passengers"])
            bus["passengers"] = []
            
            for sid in stranded_passengers:
                s = self.students[self.student_id_to_idx[sid]]
                s["status"] = "stranded"
                s["home_node"] = bus["node"] # Stranded at the breakdown node!
                s["lat"] = bus["lat"]
                s["lng"] = bus["lng"]
                s["bus_id"] = None
                
            # If the broken bus was the target of any students waiting, we reset their target
            # So they are available for other buses to pick up

    def _calculate_step_reward(self):
        # We reward/penalize based on states at the end of the step
        # Step rewards are accumulated over the episode
        return 0.0 # Standard episodic RL uses cumulative final rewards or shaped intermediate steps

    def _calculate_metrics(self):
        delivered_students = [s for s in self.students if s["status"] in ["delivered", "late"] and s["delivery_time"] is not None]
        
        # Average Ride Time
        ride_times = [s["ride_time"] for s in delivered_students]
        avg_ride_time = np.mean(ride_times) if len(ride_times) > 0 else 0.0
        
        # Neighborhood ride times for equity variance calculation
        neighborhoods = ["Fairmount", "Hillers", "Central Hackensack", "Maple Hill", "Hackensack Commons"]
        hood_avg_ride_times = []
        
        for hood in neighborhoods:
            hood_students = [s for s in delivered_students if s["neighborhood"] == hood]
            if len(hood_students) > 0:
                hood_avg = np.mean([s["ride_time"] for s in hood_students])
                hood_avg_ride_times.append(hood_avg)
                
        # Ride time variance across neighborhoods
        # (If 0 or 1 neighborhood has delivered students, variance is 0)
        if len(hood_avg_ride_times) > 1:
            ride_time_variance = np.var(hood_avg_ride_times)
        else:
            ride_time_variance = 0.0
            
        return {
            "avg_ride_time": avg_ride_time,
            "ride_time_variance": ride_time_variance
        }

    def compute_final_reward(self):
        """
        Computes the final accumulated reward for the episode.
        Highly designed to capture:
        - Delivery success
        - Lateness penalties
        - Dispatching travel time efficiency
        - Active buses used penalty
        - Equity constraints (hard ride-time limit penalty, neighborhood variance penalty)
        """
        reward = 0.0
        
        # 1. Delivery & Lateness Rewards/Penalties
        for s in self.students:
            if s["status"] == "delivered":
                reward += 100.0  # Big bonus for successful, on-time delivery
            elif s["status"] == "late":
                reward += 50.0   # Reduced bonus for late delivery
                # Penalty proportional to lateness duration
                sch = self.schools_data[s["school_id"]]
                lateness_mins = s["delivery_time"] - sch["bell_time"]
                reward -= lateness_mins * 5.0 # -5 points per minute late
            elif s["status"] in ["waiting", "stranded"]:
                reward -= 200.0  # Severe penalty for failing to pick up or deliver a student
            elif s["status"] == "absent":
                pass # No penalty for stochastically absent students (pre-notified or no-show)

        # 2. Travel Efficiency Penalty
        # Minimize total distance driven to conserve fuel
        reward -= self.total_distance * 10.0 # -10 points per mile driven
        
        # 3. Bus Consolidating Penalty (Incentive to use fewer buses)
        # Check if a bus was used (i.e. ever left the depot)
        buses_used = 0
        depot_node = self.depots_data["depot_1"]["node"]
        for bus in self.buses:
            # If the bus is not at the depot or has passengers, or has status indicating movement
            if bus["node"] != depot_node or bus["status"] != "idle" or len(bus["passengers"]) > 0:
                buses_used += 1
        reward -= buses_used * 75.0 # -75 points for each active bus used

        # 4. Equity Constraints
        metrics = self._calculate_metrics()
        
        # A. Max Ride Time Penalties (Hard ride limit: 40 minutes)
        # Any student riding for more than 40 minutes suffers major discomfort
        num_exceeding_ride_limit = sum(1 for s in self.students if s["ride_time"] > 40.0)
        reward -= num_exceeding_ride_limit * 150.0 # Massive penalty per student
        
        # B. Neighborhood Disparity Penalty (Soft constraint)
        # Penalizes standard variance of average ride times between Hackensack neighborhoods
        # Variance of 0-25 mins^2 is normal, but higher variance is heavily penalized
        reward -= metrics["ride_time_variance"] * 15.0 # -15 points per unit of variance
        
        return round(reward, 2)

    def _check_terminated(self):
        # Terminated if current time exceeds end time
        if self.current_time >= self.end_time:
            return True
            
        # Or if all students are delivered/absent/late AND all active buses are empty and at the depot
        all_students_processed = all(
            s["status"] in ["delivered", "late", "absent"] for s in self.students
        )
        depot_node = self.depots_data["depot_1"]["node"]
        all_buses_done = all(
            (b["status"] == "at_depot" or b["status"] == "broken") for b in self.buses
        )
        
        if all_students_processed and all_buses_done:
            return True
            
        return False

    def _check_early_termination(self):
        # Helper for fast environment stepping when everything is complete
        all_students_processed = all(
            s["status"] in ["delivered", "late", "absent"] for s in self.students
        )
        all_buses_done = all(
            (b["status"] == "at_depot" or b["status"] == "broken" or len(b["passengers"]) == 0)
            for b in self.buses
        )
        return all_students_processed and all_buses_done

    def _format_time(self, mins):
        h = int(mins // 60)
        m = int(mins % 60)
        ampm = "AM" if h < 12 else "PM"
        h12 = h - 12 if h > 12 else h
        return f"{h12:02d}:{m:02d} {ampm}"

    def render(self, mode="human"):
        # We will build a beautiful dedicated visualizer in visualize.py
        pass
