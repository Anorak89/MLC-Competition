import argparse
import os
import sys

# Add project path for imports
PROJECT_ROOT = "c:/VSCode_Programs/MLCComp/MLC-Competition"
sys.path.append(os.path.join(PROJECT_ROOT, "sbrp_rl"))

import numpy as np
import torch
from sbrp_env import SchoolBusRoutingEnv
from train import DQNAgent

def evaluate_model(checkpoint_path: str):
    env = SchoolBusRoutingEnv()
    # Dummy observation to infer dimensions
    dummy_obs, _ = env.reset()
    dummy_flat = env.get_flat_observation(dummy_obs)
    state_dim = dummy_flat.shape[0]
    action_dim = env.num_actions

    agent = DQNAgent(state_dim, action_dim)
    if not os.path.exists(checkpoint_path):
        print(f"Error: checkpoint file {checkpoint_path} not found.")
        return
    agent.load(checkpoint_path)
    print(f"Loaded DQN model from {checkpoint_path}")

    scores = []
    delivered = []
    lates = []
    for seed in range(50):
        obs, _ = env.reset(seed=seed)
        terminated = truncated = False
        while not (terminated or truncated):
            action_mask = obs["action_mask"]
            state_flat = env.get_flat_observation(obs)
            state_t = torch.FloatTensor(state_flat).unsqueeze(0).to(agent.device)
            agent.policy_net.eval()
            with torch.no_grad():
                q_vals = agent.policy_net(state_t).cpu().numpy()[0]
            q_vals[action_mask == 0.0] = -1e9
            action = int(np.argmax(q_vals))
            obs, _, terminated, truncated, info = env.step(action)
        final_reward = env.compute_final_reward()
        scores.append(final_reward)
        delivered.append(info["delivered_count"])
        lates.append(info["late_count"])
    print("\nTrained DQN Agent (50 Seeds):")
    print(f"  Average Reward: {np.mean(scores):.2f}")
    print(f"  Max Reward: {np.max(scores):.2f}")
    print(f"  Min Reward: {np.min(scores):.2f}")
    print(f"  Avg Delivered: {np.mean(delivered):.2f} / 30")
    print(f"  Avg Late: {np.mean(lates):.2f}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate a trained DQN checkpoint on the SBRP environment.")
    parser.add_argument("--checkpoint", type=str, default=os.path.join(PROJECT_ROOT, "models", "dqn_dispatcher.pth"), help="Path to the trained DQN checkpoint file.")
    args = parser.parse_args()
    evaluate_model(args.checkpoint)
