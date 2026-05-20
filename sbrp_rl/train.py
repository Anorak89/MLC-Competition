import os
import random
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque
import matplotlib.pyplot as plt

# Import the environment and baselines
from sbrp_env import SchoolBusRoutingEnv
from agents import NearestNeighborAgent, ORToolsStaticAgent, RandomAgent

# Set random seed for reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)

class QNetwork(nn.Module):
    """Deep Q-Network for School Bus Routing."""
    def __init__(self, input_dim, output_dim):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, output_dim)
        )

    def forward(self, x):
        return self.fc(x)


class ReplayBuffer:
    """Experience Replay Buffer."""
    def __init__(self, capacity=10000):
        self.buffer = deque(maxlen=capacity)

    def store(self, state, action, reward, next_state, done, action_mask, next_action_mask):
        self.buffer.append((state, action, reward, next_state, done, action_mask, next_action_mask))

    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones, masks, next_masks = zip(*batch)
        
        return (
            torch.FloatTensor(np.array(states)),
            torch.LongTensor(actions),
            torch.FloatTensor(rewards),
            torch.FloatTensor(np.array(next_states)),
            torch.FloatTensor(dones),
            torch.FloatTensor(np.array(masks)),
            torch.FloatTensor(np.array(next_masks))
        )

    def __len__(self):
        return len(self.buffer)


class DQNAgent:
    """Centralized DQN Agent with Action Masking."""
    def __init__(self, state_dim, action_dim, lr=1e-4, gamma=0.99, buffer_capacity=10000):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Policy and Target Networks
        self.policy_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=lr)
        self.memory = ReplayBuffer(buffer_capacity)
        
        # Exploration parameters
        self.epsilon = 0.10 # Start with 10% random exploration to preserve pre-trained policy
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.99 # smooth decay per episode

    def select_action(self, state_flat, action_mask):
        """Action Selection with Epsilon-Greedy and Action Masking."""
        # Epsilon-greedy exploration
        if random.random() < self.epsilon:
            # Choose a random valid action
            valid_actions = np.where(action_mask == 1.0)[0]
            if len(valid_actions) == 0:
                return self.action_dim - 1 # Fallback to Wait
            return random.choice(valid_actions)
        
        # Q-Network exploitation with masking
        state_t = torch.FloatTensor(state_flat).unsqueeze(0).to(self.device)
        self.policy_net.eval()
        with torch.no_grad():
            q_values = self.policy_net(state_t).cpu().numpy()[0]
            
        # Apply Action Masking
        # Set Q-values of invalid actions to a very large negative number
        q_values[action_mask == 0.0] = -1e9
        
        return int(np.argmax(q_values))

    def update(self, batch_size=64):
        """Standard Deep Q-Learning updates."""
        if len(self.memory) < batch_size:
            return
            
        self.policy_net.train()
        
        # Sample experiences
        states, actions, rewards, next_states, dones, masks, next_masks = self.memory.sample(batch_size)
        
        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)
        masks = masks.to(self.device)
        next_masks = next_masks.to(self.device)
        
        # Current Q-values
        curr_q = self.policy_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        
        # Next Q-values (Double DQN: select action with policy_net, evaluate with target_net)
        with torch.no_grad():
            # Select best actions in next states using policy network (applying mask)
            next_q_policy = self.policy_net(next_states) + (1.0 - next_masks) * -1e9
            best_actions = next_q_policy.argmax(dim=1).unsqueeze(1)
            # Evaluate these actions using target network
            next_q_target = self.target_net(next_states)
            max_next_q = next_q_target.gather(1, best_actions).squeeze(1)
            target_q = rewards + (1.0 - dones) * self.gamma * max_next_q
            
        # Compute Loss (Huber Loss is more robust than MSE)
        loss = nn.SmoothL1Loss()(curr_q, target_q)
        
        # Gradient Descent
        self.optimizer.zero_grad()
        loss.backward()
        # Gradient clipping to prevent exploding gradients
        nn.utils.clip_grad_norm_(self.policy_net.parameters(), 1.0)
        self.optimizer.step()

    def update_target_network(self):
        self.target_net.load_state_dict(self.policy_net.state_dict())

    def save(self, filepath):
        torch.save(self.policy_net.state_dict(), filepath)

    def load(self, filepath):
        self.policy_net.load_state_dict(torch.load(filepath, map_location=self.device))
        self.target_net.load_state_dict(self.policy_net.state_dict())


def evaluate_agent(env, agent=None, name="Agent", verbose=True, seeds=[12, 22, 32, 42, 52]):
    """Evaluates an agent on multiple seeds and returns the average reward and average info."""
    rewards = []
    delivered_list = []
    late_list = []
    absent_list = []
    mileage_list = []
    equity_list = []
    
    for seed in seeds:
        obs_dict, info = env.reset(seed=seed)
        terminated = False
        truncated = False
        
        agent_reset = getattr(agent, "reset", None)
        if agent_reset:
            agent.reset()
            
        while not (terminated or truncated):
            active_bus_idx = obs_dict["active_bus_idx"]
            action_mask = obs_dict["action_mask"]
            
            if agent is None:
                action = env.action_space.sample()
            elif isinstance(agent, DQNAgent):
                state_flat = env.get_flat_observation(obs_dict)
                state_t = torch.FloatTensor(state_flat).unsqueeze(0).to(agent.device)
                agent.policy_net.eval()
                with torch.no_grad():
                    q_values = agent.policy_net(state_t).cpu().numpy()[0]
                q_values[action_mask == 0.0] = -1e9
                action = int(np.argmax(q_values))
            else:
                action = agent.decide(obs_dict, info, env)
                
            obs_dict, step_reward, terminated, truncated, info = env.step(action)
            
        final_reward = env.compute_final_reward()
        rewards.append(final_reward)
        delivered_list.append(info['delivered_count'])
        late_list.append(info['late_count'])
        absent_list.append(info['absent_count'])
        mileage_list.append(info['total_distance'])
        equity_list.append(info['equity_variance'])
        
    avg_reward = float(np.mean(rewards))
    avg_info = {
        "delivered_count": float(np.mean(delivered_list)),
        "late_count": float(np.mean(late_list)),
        "absent_count": float(np.mean(absent_list)),
        "total_distance": float(np.mean(mileage_list)),
        "equity_variance": float(np.mean(equity_list))
    }
    
    if verbose:
        print(f"--- {name} Multi-Seed Evaluation ({len(seeds)} Seeds) ---")
        print(f"Average Cumulative Reward: {avg_reward:.2f}")
        print(f"Avg Delivered: {avg_info['delivered_count']:.2f} / {env.num_students} (Late: {avg_info['late_count']:.2f}, Absent: {avg_info['absent_count']:.2f})")
        print(f"Avg Mileage: {avg_info['total_distance']:.2f} miles")
        print(f"Avg Equity Variance: {avg_info['equity_variance']:.2f} mins^2")
        
    return avg_reward, avg_info

def pretrain_agent(env, agent, num_episodes=50):
    """
    Runs supervised Q-Value Regression on the NearestNeighborAgent
    to initialize the DQN agent's Q-network weights with the exact scale
    and magnitude of real VRP cumulative returns, and pre-fills the
    agent's replay buffer with these expert demonstration transitions.
    """
    print(f"\nPre-training Q-Network on Nearest Neighbor Heuristic for {num_episodes} episodes...")
    nn_agent = NearestNeighborAgent()
    
    states_dataset = []
    actions_dataset = []
    returns_dataset = []
    masks_dataset = []
    
    # 1. Collect demonstration data with actual discounted returns
    for ep in range(num_episodes):
        obs_dict, info = env.reset(seed=SEED + ep) # vary seed slightly for diverse states
        terminated = False
        truncated = False
        
        episode_transitions = []
        
        while not (terminated or truncated):
            action_mask = obs_dict["action_mask"]
            action = nn_agent.decide(obs_dict, info, env)
            state_flat = env.get_flat_observation(obs_dict)
            
            # Step the environment to get the shaped step reward
            prev_student_statuses = [s["status"] for s in env.students]
            prev_distance = env.total_distance
            
            next_obs_dict, step_reward, terminated, truncated, info = env.step(action)
            next_state_flat = env.get_flat_observation(next_obs_dict)
            next_action_mask = next_obs_dict["action_mask"]
            
            # Compute mathematically consistent shaped step reward
            shaped_reward = 0.0
            step_distance = env.total_distance - prev_distance
            shaped_reward -= step_distance * 10.0
            if action_mask[action] == 0.0:
                shaped_reward -= 100.0
                
            for s_idx, student in enumerate(env.students):
                prev_status = prev_student_statuses[s_idx]
                curr_status = student["status"]
                if prev_status in ["waiting", "stranded"] and curr_status == "picked_up":
                    shaped_reward += 80.0 if prev_status == "stranded" else 50.0
                if prev_status == "picked_up" and curr_status in ["delivered", "late"]:
                    if curr_status == "delivered":
                        shaped_reward += 250.0
                    else:
                        sch = env.schools_data[student["school_id"]]
                        lateness_mins = student["delivery_time"] - sch["bell_time"]
                        shaped_reward += max(0.0, 200.0 - lateness_mins * 5.0)
            
            episode_transitions.append({
                "state": state_flat,
                "action": action,
                "reward": shaped_reward,
                "next_state": next_state_flat,
                "done": float(terminated),
                "mask": action_mask,
                "next_mask": next_action_mask
            })
            
            obs_dict = next_obs_dict
            
        # Add the global sparse reward difference to the last transition of this episode
        final_vrp_reward = env.compute_final_reward()
        sum_shaped_rewards = sum([t["reward"] for t in episode_transitions])
        diff = final_vrp_reward - sum_shaped_rewards
        if len(episode_transitions) > 0:
            episode_transitions[-1]["reward"] += diff
            
        # Store these expert transitions into the agent's replay memory!
        for t in episode_transitions:
            agent.memory.store(
                t["state"],
                t["action"],
                t["reward"],
                t["next_state"],
                t["done"],
                t["mask"],
                t["next_mask"]
            )
            
        # Now compute discounted returns G_t for supervised value regression
        G = 0.0
        for t in reversed(range(len(episode_transitions))):
            G = episode_transitions[t]["reward"] + agent.gamma * G
            episode_transitions[t]["return"] = G
            
        # Append to dataset
        for t in episode_transitions:
            states_dataset.append(t["state"])
            actions_dataset.append(t["action"])
            returns_dataset.append(t["return"])
            masks_dataset.append(t["mask"])
            
    states_t = torch.FloatTensor(np.array(states_dataset)).to(agent.device)
    actions_t = torch.LongTensor(actions_dataset).to(agent.device)
    returns_t = torch.FloatTensor(returns_dataset).to(agent.device)
    masks_t = torch.FloatTensor(np.array(masks_dataset)).to(agent.device)
    
    num_samples = len(states_dataset)
    print(f"Collected {num_samples} expert demonstration transitions and pre-filled the replay buffer.")
    
    # 2. Run supervised DQfD Large Margin + Q-Value Regression joint pre-training
    agent.policy_net.train()
    batch_size = 64
    epochs = 30
    optimizer = optim.Adam(agent.policy_net.parameters(), lr=1e-3)
    loss_fn = nn.SmoothL1Loss() # Huber Loss for the value regression anchor
    
    for epoch in range(epochs):
        permutation = torch.randperm(num_samples)
        epoch_loss = 0.0
        
        for i in range(0, num_samples, batch_size):
            indices = permutation[i:i+batch_size]
            batch_states = states_t[indices]
            batch_actions = actions_t[indices]
            batch_returns = returns_t[indices]
            batch_masks = masks_t[indices]
            
            # Get Q-values from policy network
            q_values = agent.policy_net(batch_states)
            
            # A. Value regression anchor on the expert action
            expert_q = q_values.gather(1, batch_actions.unsqueeze(1)).squeeze(1)
            reg_loss = loss_fn(expert_q, batch_returns)
            
            # B. Large Margin Classification Loss (DQfD style)
            margin = 150.0
            # 150.0 for valid actions, and -1e9 for invalid actions so they are ignored in the max
            margin_tensor = torch.where(batch_masks == 1.0, torch.tensor(margin).to(agent.device), torch.tensor(-1e9).to(agent.device))
            # The expert action gets a margin of 0.0
            margin_tensor.scatter_(1, batch_actions.unsqueeze(1), 0.0)
            
            # Compute Q(s, a) + margin
            q_plus_margin = q_values + margin_tensor
            # Take the max over all actions
            max_q_plus_margin, _ = q_plus_margin.max(dim=1)
            
            # Margin loss penalizes if any other valid action Q-value is too close to or greater than expert Q-value
            margin_loss = torch.mean(max_q_plus_margin - expert_q)
            
            # Joint loss: balanced weighting
            loss = reg_loss + 1.0 * margin_loss
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item() * len(indices)
            
        avg_loss = epoch_loss / num_samples
        if (epoch + 1) % 5 == 0 or epoch == 0 or epoch == epochs - 1:
            print(f"  Q-Reg Epoch {epoch+1:02d}/{epochs:02d} | Joint Huber-Margin Loss: {avg_loss:.4f}")
        
    # Copy weights to target network
    agent.update_target_network()
    print("Pre-training complete! Q-Network weights initialized with Nearest Neighbor expected returns and safe margin bounds.")


def main():
    print("Initializing environment...")
    env = SchoolBusRoutingEnv()
    
    # 1. Run baseline agents to see their scores
    print("\nRunning Baselines...")
    random_agent = RandomAgent()
    nn_agent = NearestNeighborAgent()
    static_agent = ORToolsStaticAgent()
    
    evaluate_agent(env, random_agent, "Random Agent")
    evaluate_agent(env, nn_agent, "Nearest Neighbor Heuristic")
    evaluate_agent(env, static_agent, "OR-Tools Static Baseline")

    # 2. Set up DQN Training
    dummy_obs_dict, _ = env.reset()
    dummy_flat_obs = env.get_flat_observation(dummy_obs_dict)
    state_dim = dummy_flat_obs.shape[0]
    action_dim = env.num_actions
    
    print(f"\nState Dimension (Flat Observation): {state_dim}")
    print(f"Action Dimension (Output Actions): {action_dim}")
    
    agent = DQNAgent(state_dim, action_dim, buffer_capacity=20000)
    
    # 3. Supervised Pre-training (Behavior Cloning)
    pretrain_agent(env, agent, num_episodes=50)
    
    # Evaluate pre-trained agent before RL to check behavior cloning quality
    best_reward, _ = evaluate_agent(env, agent, "Pre-trained DQN Agent (Heuristic initialized)", verbose=True)
    
    os.makedirs("models", exist_ok=True)
    model_path = "models/dqn_dispatcher.pth"
    agent.save(model_path)
    print(f"Initial best reward set to {best_reward:.2f}. Saved baseline checkpoint.")
    
    num_episodes = 350
    batch_size = 64
    target_update_frequency = 5 # target net updates every 5 episodes
    
    print(f"\nTraining DQN Centralized Dispatcher for {num_episodes} episodes...")
    
    rewards_history = []
    delivered_history = []
    
    for ep in range(1, num_episodes + 1):
        obs_dict, info = env.reset()
        state_flat = env.get_flat_observation(obs_dict)
        
        terminated = False
        truncated = False
        
        ep_step = 0
        
        while not (terminated or truncated):
            active_bus_idx = obs_dict["active_bus_idx"]
            action_mask = obs_dict["action_mask"]
            
            # Select action
            action = agent.select_action(state_flat, action_mask)
            
            # Keep track of states before the step to shape intermediate rewards
            prev_student_statuses = [s["status"] for s in env.students]
            prev_distance = env.total_distance
            
            # Step the environment
            next_obs_dict, step_reward, terminated, truncated, info = env.step(action)
            next_state_flat = env.get_flat_observation(next_obs_dict)
            next_action_mask = next_obs_dict["action_mask"]
            
            # 1. Compute mathematically consistent shaped step reward
            shaped_reward = 0.0
            
            # Travel mileage cost (-10.0 per mile driven in this step)
            step_distance = env.total_distance - prev_distance
            shaped_reward -= step_distance * 10.0
            
            # Action mask violation penalty
            if action_mask[action] == 0.0:
                shaped_reward -= 100.0
                
            # Student pickup and delivery rewards
            for s_idx, student in enumerate(env.students):
                prev_status = prev_student_statuses[s_idx]
                curr_status = student["status"]
                
                # A. Successful student pickup
                if prev_status in ["waiting", "stranded"] and curr_status == "picked_up":
                    if prev_status == "stranded":
                        shaped_reward += 80.0  # High bonus for rescuing a stranded student!
                    else:
                        shaped_reward += 50.0  # Standard student pickup bonus
                        
                # B. Successful student delivery
                if prev_status == "picked_up" and curr_status in ["delivered", "late"]:
                    if curr_status == "delivered":
                        shaped_reward += 250.0  # Big bonus for on-time delivery (total +300.0)
                    else:
                        sch = env.schools_data[student["school_id"]]
                        lateness_mins = student["delivery_time"] - sch["bell_time"]
                        # Late delivery bonus (200.0 minus 5.0 per minute late, total +250.0 relative to undelivered)
                        shaped_reward += max(0.0, 200.0 - lateness_mins * 5.0)
            
            # Store in replay buffer
            agent.memory.store(
                state_flat, 
                action, 
                shaped_reward, 
                next_state_flat, 
                float(terminated), 
                action_mask, 
                next_action_mask
            )
            
            state_flat = next_state_flat
            obs_dict = next_obs_dict
            ep_step += 1
            
            # Run one network update step
            agent.update(batch_size)
 
        # After the episode ends, we compute the real episodic VRP reward
        final_vrp_reward = env.compute_final_reward()
        
        # Calculate sum of shaped rewards from this episode
        num_stored = len(agent.memory.buffer)
        sum_shaped_rewards = 0.0
        for i in range(num_stored - ep_step, num_stored):
            if i >= 0:
                sum_shaped_rewards += agent.memory.buffer[i][2] # index 2 is reward
                
        # The difference accounts for global sparse terms (variance, bus usage, undelivered, constant offset)
        diff = final_vrp_reward - sum_shaped_rewards
        
        # Add the entire difference to the final transition of this episode
        # This keeps intermediate step rewards clean and avoids gradient noise/policy corruption,
        # while mathematically ensuring that the sum of returns exactly equals the true VRP reward.
        if num_stored > 0:
            s, a, r, ns, d, m, nm = agent.memory.buffer[-1]
            agent.memory.buffer[-1] = (s, a, r + diff, ns, d, m, nm)
        
        # Decay exploration
        agent.epsilon = max(agent.epsilon_min, agent.epsilon * agent.epsilon_decay)
        
        # Target network update
        if ep % target_update_frequency == 0:
            agent.update_target_network()
            
        rewards_history.append(final_vrp_reward)
        delivered_history.append(info["delivered_count"])
        
        if ep % 10 == 0:
            print(f"Episode {ep:03d} | Epsilon: {agent.epsilon:.2f} | VRP Reward: {final_vrp_reward:7.1f} | Delivered: {info['delivered_count']:2d}/{env.num_students} (Late: {info['late_count']})")
            
        # Periodically evaluate and save checkpoint if this is the best model so far
        if ep % 20 == 0:
            eval_reward, _ = evaluate_agent(env, agent, name=f"Ep {ep}", verbose=False)
            if eval_reward > best_reward:
                best_reward = eval_reward
                agent.save(model_path)
                print(f"  [Checkpoint] Episode {ep:03d} | New Best VRP Reward: {best_reward:.2f} | Saved checkpoint!")

    # Evaluate the trained agent
    print("\nTraining complete!")
    
    # Load the best checkpointed model for final evaluation
    if os.path.exists(model_path):
        print(f"Loading best checkpointed model from {model_path} with reward {best_reward:.2f}...")
        agent.load(model_path)
        
    dqn_final_reward, dqn_info = evaluate_agent(env, agent, "Trained DQN Agent")
    
    # Plot training curves
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.plot(rewards_history, color="#3b82f6", linewidth=1.5)
    plt.title("DQN VRP Cumulative Reward")
    plt.xlabel("Episode")
    plt.ylabel("Reward")
    plt.grid(True, linestyle="--", alpha=0.6)
    
    plt.subplot(1, 2, 2)
    plt.plot(delivered_history, color="#10b981", linewidth=1.5)
    plt.title("Delivered Students Count")
    plt.xlabel("Episode")
    plt.ylabel("Count")
    plt.grid(True, linestyle="--", alpha=0.6)
    
    os.makedirs("plots", exist_ok=True)
    plt.savefig("plots/dqn_training_curves.png", dpi=150, bbox_inches="tight")
    print("Saved training performance curves to plots/dqn_training_curves.png")

if __name__ == "__main__":
    main()
