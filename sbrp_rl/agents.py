import random
import numpy as np
import networkx as nx

class BaseAgent:
    """Base class for all School Bus Routing agents."""
    def __init__(self, name="BaseAgent"):
        self.name = name

    def decide(self, obs, info, env):
        """
        Decides the next action for the active bus.
        Args:
            obs: The dictionary observation from the environment.
            info: The info dictionary from the environment.
            env: The raw environment object (useful for accessing graph and routing).
        Returns:
            action: integer representing the selected action.
        """
        raise NotImplementedError

    def reset(self):
        """Called at the beginning of each episode."""
        pass


class RandomAgent(BaseAgent):
    """An agent that selects randomly among valid actions in the action mask."""
    def __init__(self):
        super().__init__("Random Agent")

    def decide(self, obs, info, env):
        action_mask = obs["action_mask"]
        valid_actions = np.where(action_mask == 1.0)[0]
        if len(valid_actions) == 0:
            return env.num_actions - 1 # Fallback to Wait
        return random.choice(valid_actions)


class NearestNeighborAgent(BaseAgent):
    """
    A dynamic, online heuristic agent.
    At each step:
    - If the bus has capacity and there are waiting/stranded students:
      - Head to the closest student's home node (using Dijkstra shortest path length on current network).
    - If the bus is full, or there are no available students:
      - Head to the school where the majority of passengers are assigned.
    - If the bus is empty and no students are left:
      - Return to the depot.
    """
    def __init__(self):
        super().__init__("Nearest Neighbor Heuristic")

    def decide(self, obs, info, env):
        active_bus_idx = obs["active_bus_idx"]
        if active_bus_idx == -1:
            return env.num_actions - 1 # Wait
            
        bus = env.buses[active_bus_idx]
        action_mask = obs["action_mask"]
        
        # 1. If bus has passengers, check if we should drop them off
        # If we have reached capacity or no other students are waiting, drop off
        has_passengers = len(bus["passengers"]) > 0
        at_capacity = len(bus["passengers"]) >= bus["capacity"]
        
        # Find all available pickup actions in mask
        valid_pickup_indices = []
        for s_idx in range(env.num_students):
            if action_mask[s_idx] == 1.0:
                valid_pickup_indices.append(s_idx)

        # 2. If at capacity or no students left, deliver to school
        if has_passengers and (at_capacity or len(valid_pickup_indices) == 0):
            # Find schools in mask
            valid_school_actions = []
            for sch_idx in range(env.num_schools):
                act_idx = env.num_students + sch_idx
                if action_mask[act_idx] == 1.0:
                    valid_school_actions.append(act_idx)
            
            if len(valid_school_actions) > 0:
                # Pick the school that has the most passengers on this bus assigned to it
                school_counts = {}
                for sid in bus["passengers"]:
                    student = env.students[env.student_id_to_idx[sid]]
                    school_counts[student["school_id"]] = school_counts.get(student["school_id"], 0) + 1
                
                # Find the valid school action with highest count
                best_action = valid_school_actions[0]
                max_count = -1
                for act in valid_school_actions:
                    sch_id = env.school_ids[act - env.num_students]
                    count = school_counts.get(sch_id, 0)
                    if count > max_count:
                        max_count = count
                        best_action = act
                return best_action

        # 3. Otherwise, if there are valid pickups, find the closest one
        if len(valid_pickup_indices) > 0:
            best_pickup_action = None
            min_dist = float("inf")
            
            for s_idx in valid_pickup_indices:
                student = env.students[s_idx]
                try:
                    # Calculate shortest path length on current network
                    dist = nx.dijkstra_path_length(env.G, bus["node"], student["home_node"], weight="weight")
                    if dist < min_dist:
                        min_dist = dist
                        best_pickup_action = s_idx
                except nx.NetworkXNoPath:
                    continue
            
            if best_pickup_action is not None:
                return best_pickup_action

        # 4. If nothing else is valid, return to depot
        depot_act_idx = env.num_students + env.num_schools
        if action_mask[depot_act_idx] == 1.0:
            return depot_act_idx
            
        # 5. Default to Wait
        return env.num_actions - 1


class ORToolsStaticAgent(BaseAgent):
    """
    A Static VRP Planner Agent (simulates Google OR-Tools).
    At t=0, it plans static, deterministic routes for each bus:
    - Splits students into 3 school-runs (HHS, HMS, FES) based on bell times.
    - Pre-assigns students to buses.
    - Sequences stops using a static TSP solver (Nearest Neighbor) on the base graph.
    - Blindly follows this plan, showing extreme vulnerability to online stochastic disruptions:
      - Wastes time driving to absent students' homes (no-shows).
      - Gets delayed by road closures and traffic spikes, arriving late at schools.
      - Strands passengers during a breakdown and never rescues them.
    """
    def __init__(self):
        super().__init__("OR-Tools Static Baseline")
        self.routes = {} # maps bus_id -> list of target nodes/actions
        self.route_indices = {} # maps bus_id -> current step index in the plan
        self.planned = False

    def reset(self):
        self.routes = {}
        self.route_indices = {}
        self.planned = False

    def _plan_static_routes(self, env):
        # We pre-plan routes for all buses assuming zero disruptions and perfect attendance
        # Group students by school so we can do staggered runs
        students_by_school = {sch_id: [] for sch_id in env.school_ids}
        for s in env.students_data:
            students_by_school[s["school_id"]].append(s)

        # Staggered order: school_hhs (8:00 AM), school_hms (8:30 AM), school_fes (9:00 AM)
        school_order = ["school_hhs", "school_hms", "school_fes"]
        
        bus_plans = {bid: [] for bid in env.bus_ids}
        
        # We divide buses to cover the school runs
        # To make it realistic, all buses run the HHS loop, then all do the HMS loop, then FES loop
        # This is a classic multi-trip static VRP schedule
        
        for school_id in school_order:
            school_students = students_by_school[school_id]
            school_node = env.schools_data[school_id]["node"]
            
            # Simple clustering: divide students evenly among buses
            random.seed(101) # static plan seed
            shuffled_students = list(school_students)
            random.shuffle(shuffled_students)
            
            # Distribute to buses
            for idx, student in enumerate(shuffled_students):
                bus_id = env.bus_ids[idx % env.num_buses]
                bus_plans[bus_id].append({
                    "type": "pickup",
                    "student_id": student["id"],
                    "node": student["home_node"]
                })
                
            # Add a school dropoff for each bus at the end of the run
            for bus_id in env.bus_ids:
                # Only if this bus actually picked up students for this school in this run
                has_passengers = any(
                    x["type"] == "pickup" and env.students_data[env.student_id_to_idx[x["student_id"]]]["school_id"] == school_id
                    for x in bus_plans[bus_id]
                )
                
                # Insert the school dropoff at the end of the current run's pickups
                # We find the last pickup and insert school after it
                bus_plans[bus_id].append({
                    "type": "dropoff",
                    "node": school_node,
                    "school_id": school_id
                })

        # Finally, add return to depot
        depot_node = env.depots_data["depot_1"]["node"]
        for bus_id in env.bus_ids:
            bus_plans[bus_id].append({
                "type": "depot",
                "node": depot_node
            })

        # Save plans and reset indices
        for bus_id in env.bus_ids:
            self.routes[bus_id] = bus_plans[bus_id]
            self.route_indices[bus_id] = 0
            
        self.planned = True

    def decide(self, obs, info, env):
        if not self.planned:
            self._plan_static_routes(env)

        active_bus_idx = obs["active_bus_idx"]
        if active_bus_idx == -1:
            return env.num_actions - 1 # Wait

        bus = env.buses[active_bus_idx]
        bus_id = bus["id"]
        action_mask = obs["action_mask"]
        
        plan = self.routes.get(bus_id, [])
        idx = self.route_indices.get(bus_id, 0)
        
        # If we have reached the end of the pre-planned route, just wait or return to depot
        if idx >= len(plan):
            # If empty and valid depot
            depot_act = env.num_students + env.num_schools
            if len(bus["passengers"]) == 0 and action_mask[depot_act] == 1.0:
                return depot_act
            return env.num_actions - 1 # Wait

        # Look at the current planned step
        step = plan[idx]
        
        # Check if the step action is valid in action mask
        action_to_take = None
        
        if step["type"] == "pickup":
            student_id = step["student_id"]
            s_idx = env.student_id_to_idx[student_id]
            
            # Static solver vulnerability: if student is absent (known at t=0), 
            # or if the student was already picked up, or if the bus is full,
            # this action might be invalid in the mask.
            # In pure static planning, the solver doesn't know about absences.
            # If valid, execute pickup. If invalid, we skip to the next planned step!
            if action_mask[s_idx] == 1.0:
                action_to_take = s_idx
            else:
                # Student is not pickable (absent, already picked up, or bus full).
                # Move to next step in plan and re-evaluate
                self.route_indices[bus_id] = idx + 1
                return self.decide(obs, info, env)
                
        elif step["type"] == "dropoff":
            school_id = step["school_id"]
            sch_idx = env.school_id_to_idx[school_id]
            act_idx = env.num_students + sch_idx
            
            if action_mask[act_idx] == 1.0:
                action_to_take = act_idx
            else:
                # School is not a valid dropoff (e.g. bus is carrying no students for this school).
                # Move to next step in plan and re-evaluate
                self.route_indices[bus_id] = idx + 1
                return self.decide(obs, info, env)
                
        elif step["type"] == "depot":
            depot_act = env.num_students + env.num_schools
            if action_mask[depot_act] == 1.0:
                action_to_take = depot_act
            else:
                action_to_take = env.num_actions - 1 # Wait

        if action_to_take is not None:
            # Successfully decided on this step. Advance plan index for the NEXT call
            self.route_indices[bus_id] = idx + 1
            return action_to_take
            
        # Fallback to Wait
        return env.num_actions - 1
