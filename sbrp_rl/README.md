# Reinforcement Learning School Bus Routing Competition
## 🚌 Destination: Hackensack, New Jersey

Welcome to the **School Bus Routing Problem (SBRP)** Reinforcement Learning Competition! 

Every single morning, school districts across the country face a massive logistical headache: picking up thousands of students and delivering them to their schools safely, equitably, and on time. You have a fixed number of buses, strict capacity limits, staggered school bell times, and an unpredictable, living city to navigate. 

This sounds simple, but it is actually a variant of the **Vehicle Routing Problem (VRP)**—one of the most famous, heavily studied, and hardest NP-hard combinatorial optimization problems in computer science. Standard algorithms like Google OR-Tools or A* search can build perfect static plans, but they break down completely when the real world gets messy. 

This is exactly why **Reinforcement Learning (RL)** is a compelling approach: it learns closed-loop policies that can adapt, coordinate, and make smart, real-time dispatching decisions under severe uncertainty.

---

## 🏆 The Challenge

You are the Lead Dispatcher for the Hackensack, NJ School District. Your fleet has **3 school buses** (capacity of 12 students each) starting at the **Hackensack Bus Yard (Depot)**. You must pick up and deliver **30 students** divided across **5 neighborhoods** (Fairmount, Hillers, Central, Maple Hill, and Hackensack Commons) to **3 different schools** with staggered starting times (bell times):

1. 🍎 **Hackensack High School (HHS)** — Bell Time: 8:00 AM (480 mins) | Student windows: 7:15 - 7:35 AM
2. 🏫 **Hackensack Middle School (HMS)** — Bell Time: 8:30 AM (510 mins) | Student windows: 7:45 - 8:05 AM
3. ✏️ **Fairmount Elementary School (FES)** — Bell Time: 9:00 AM (540 mins) | Student windows: 8:15 - 8:35 AM

The morning begins at **7:00 AM (420 mins)** and concludes at **9:30 AM (570 mins)**.

---

## 🚨 Why Classical Static Optimization (Google OR-Tools) Fails

If this were a quiet, static problem, classical solvers would win. But Hackensack is dynamic:

*   💥 **Bus Breakdowns**: Stochastically, a bus will suffer a mechanical failure. It halts, and its passengers are left **stranded** on the road network. A static pre-plan will leave them stranded forever. An RL agent must dynamically coordinate other active buses to deviate, rescue the stranded students, and still make their own school bell times.
*   ⚠️ **Dynamic Road Closures**: Mid-route, an accident will shut down a major street segment. Buses must instantly reroute. Under static schedules, this causes massive cascading delays.
*   🚗 **Morning Rush-Hour Traffic**: Between 7:30 and 8:30 AM, traffic multipliers on main roads spike up to **2.2x**, stochastically shifting travel times.
*   ❓ **Stochastic Student Attendance & No-Shows**: Some students are absent. Parents might call in early (pre-notified at 7:00 AM), but others are **no-shows**—the bus drives all the way to their house, waits for a minute, and only then discovers they aren't there. Static planners waste valuable time traveling to absent students.
*   ⚖️ **Highly Non-Linear Equity Constraints**: Standard solvers struggle with non-linear objectives. Your reward function includes a penalty on the **variance of average ride times across neighborhoods**. This prevents the system from giving short rides to central neighborhoods while leaving outer neighborhoods with exhausting 40+ minute rides.

---

## 🤖 The Reinforcement Learning Formulation

The environment is built using the industry-standard **Gymnasium** (Gym) interface.

### 1. State (Observation) Space
At each decision step, the active bus observes:
*   `time`: Current clock time (normalized).
*   `active_bus_idx`: Which bus currently needs a route assignment.
*   `bus_states`: `[lat, lng, occupancy_pct, status_code, time_remaining]` for all buses.
*   `student_states`: `[lat, lng, school_idx, status_code, window_start, window_end]` for all 30 students.
*   `disruptions`: Real-time traffic congestion factor and road closure markers for all edges.
*   `action_mask`: A binary mask indicating which next moves are physically valid.

### 2. Event-Driven Action Space (SMDP)
Instead of deciding what a bus should do second-by-second, the environment uses a **Semi-Markov Decision Process (SMDP)**. Whenever a bus completes its current path and becomes idle, the simulation pauses and asks the centralized RL dispatcher for a **single discrete action** representing the bus's next target destination:
*   `0 to 29`: Pick up student $i$ at their home node (or stranded node).
*   `30`: Deliver passengers to **Hackensack High School**.
*   `31`: Deliver passengers to **Hackensack Middle School**.
*   `32`: Deliver passengers to **Fairmount Elementary School**.
*   `33`: Return empty to the **Bus Depot** (finishes the day for this bus).
*   `34`: **Wait** at the current node for 5 minutes (useful if waiting for a student's pickup window to open).

### 3. The Objective Function (Reward)
Your cumulative final reward is a blend of efficiency, reliability, and social equity:
*   ➕ **+$100$** for every student delivered safely and on time.
*   ➕ **+$50$** for every student delivered late.
*   ➖ **-$5$ per minute** a student is late.
*   ➖ **-$200$** for failing to pick up or deliver a student.
*   ➖ **-$10$ per mile** driven (incentivizes shorter routes).
*   ➖ **-$75$ per active bus used** (incentivizes consolidation—can you do it with 2 buses?).
*   ➖ **-$150$** for any student whose ride time exceeds **40 minutes** (Hard Ride-Time Limit).
*   ➖ **-$15 \times \text{Variance(Neighborhood Ride Times)}$** (Social Equity Penalty).

---

## 🚀 How to Run and Train

### Prerequisites
Install the lightweight dependencies:
```bash
pip install gymnasium numpy networkx torch matplotlib
```

### 1. Run and Compare the Baselines
We have provided three built-in baselines in `agents.py`:
*   `RandomAgent`: Blindly picks valid destinations.
*   `NearestNeighborAgent`: A greedy online heuristic (highly competitive!).
*   `ORToolsStaticAgent`: A static VRP scheduler simulating classical solvers (Clarke-Wright savings).

Run the training/evaluation script:
```bash
python train.py
```
*Observe how the OR-Tools static agent does well on a quiet day, but its score **crashes catastrophically** when stochastically absent students, road closures, and bus breakdowns are introduced!*

### 2. Visualize the Action in Real-Time!
We have built a stunning, custom Matplotlib visualizer showing the Hackensack street network, school bell timers, real-time road closures (in red), traffic spikes (dark red arterials), stranded student rescues, and a running metrics dashboard.

Run the visualizer with different agents:
```bash
# Watch the Greedy Online Heuristic
python visualize.py --agent nn

# Watch the Static OR-Tools Baseline crash on breakdowns/closures
python visualize.py --agent static

# Watch your trained Reinforcement Learning agent!
python visualize.py --agent dqn
```

---

## 💡 Advanced Strategies to Win

To get the absolute highest reward and defeat the heuristics, try implementing:
1.  🛡️ **Action Masking**: We have built an `action_mask` directly into the observation. Make sure your RL policy uses this mask to set the probabilities/Q-values of invalid actions to 0 or $-\infty$ before selection, which speeds up training by 10x!
2.  🎨 **Reward Shaping**: The environment provides a cumulative final reward. For training algorithms like DQN or PPO, design intermediate, dense step rewards (e.g., small positive rewards for successful pickups, small penalties for minutes buses spend driving) to guide exploration.
3.  🧠 **PPO or Actor-Critic**: While we provided a starter PyTorch DQN, policy gradient methods like **Proximal Policy Optimization (PPO)** combined with an Actor-Critic architecture perform exceptionally well on structured vehicle routing environments.
4.  🤝 **Multi-Agent RL (MARL)**: Reframe the problem so that each bus is an independent agent trying to cooperate via shared observations, using libraries like PettingZoo or Ray/RLLib.
