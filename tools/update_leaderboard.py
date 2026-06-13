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
    
    now = datetime.now(timezone.utc)
    new_timestamp = now.isoformat()
    
    DATA_FILE = 'data/leaderboard.json'
    
    # Check existing data to see if it changed
    existing_data = None
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                existing_data = json.load(f)
        except Exception:
            pass

    data_changed = True
    if existing_data:
        old_final = existing_data.get(str(FINAL_PHASE))
        old_dev = existing_data.get(str(DEV_PHASE))
        if old_final == final_data and old_dev == dev_data:
            data_changed = False

    # If data hasn't changed and it's the same day, keep the existing timestamp
    if not data_changed and existing_data and 'last_updated' in existing_data:
        old_timestamp_str = existing_data['last_updated']
        try:
            old_time = datetime.fromisoformat(old_timestamp_str.replace('Z', '+00:00'))
            if old_time.date() == now.date():
                new_timestamp = old_timestamp_str
        except Exception:
            pass
    
    # Store data with the calculated timestamp
    leaderboard_data = {
        str(FINAL_PHASE): final_data,
        str(DEV_PHASE): dev_data,
        "last_updated": new_timestamp
    }
    
    os.makedirs('data', exist_ok=True)
    
    with open(DATA_FILE, 'w') as f:
        json.dump(leaderboard_data, f, indent=2)
        
    print("Successfully updated data/leaderboard.json")

if __name__ == "__main__":
    main()
