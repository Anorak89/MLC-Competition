import urllib.request
import json
import os
from datetime import datetime, timezone

FINAL_PHASE = 28294
DEV_PHASE = 28293

def fetch_phase(phase_id):
    url = f"https://www.codabench.org/api/phases/{phase_id}/get_leaderboard/"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching phase {phase_id}: {e}")
        return None

def main():
    final_data = fetch_phase(FINAL_PHASE)
    dev_data = fetch_phase(DEV_PHASE)
    
    # Store data with a timestamp
    leaderboard_data = {
        str(FINAL_PHASE): final_data,
        str(DEV_PHASE): dev_data,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    
    os.makedirs('data', exist_ok=True)
    
    with open('data/leaderboard.json', 'w') as f:
        json.dump(leaderboard_data, f, indent=2)
        
    print("Successfully updated data/leaderboard.json")

if __name__ == "__main__":
    main()
