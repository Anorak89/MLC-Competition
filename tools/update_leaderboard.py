import urllib.request
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FINAL_PHASE = 28294
DEV_PHASE = 28293

def fetch_phase(phase_id):
    url = f"https://www.codabench.org/api/phases/{phase_id}/get_leaderboard/"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req) as response:
            raw_data = json.loads(response.read().decode())
            
            # Prune data to only what the website shows
            pruned_submissions = []
            for sub in raw_data.get('submissions', []):
                pruned_scores = []
                for s in sub.get('scores', []):
                    if s.get('column_key') in ['score', 'mean_reward', 'episodes']:
                        pruned_scores.append({
                            'column_key': s.get('column_key'),
                            'score': s.get('score')
                        })
                pruned_submissions.append({
                    'owner': sub.get('owner', 'Unknown'),
                    'scores': pruned_scores
                })
                
            return {'submissions': pruned_submissions}
    except Exception as e:
        print(f"Error fetching phase {phase_id}: {e}")
        return None

def main():
    final_data = fetch_phase(FINAL_PHASE)
    final_has_data = bool(final_data and final_data.get('submissions'))
    
    dev_data = None
    if not final_has_data:
        dev_data = fetch_phase(DEV_PHASE)
    
    now_utc = datetime.now(timezone.utc)
    new_timestamp = now_utc.isoformat()
    
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

    # If data hasn't changed and it's the same day in Eastern Time, do nothing
    if not data_changed and existing_data and 'last_updated' in existing_data:
        old_timestamp_str = existing_data['last_updated']
        try:
            old_time_utc = datetime.fromisoformat(old_timestamp_str.replace('Z', '+00:00'))
            
            eastern = ZoneInfo("America/New_York")
            old_time_est = old_time_utc.astimezone(eastern)
            now_est = now_utc.astimezone(eastern)
            
            if old_time_est.date() == now_est.date():
                print("No changes in leaderboard data and still the same day (EST). Skipping write.")
                return
        except Exception:
            pass
    
    # Store data with the calculated timestamp
    leaderboard_data = {
        str(FINAL_PHASE): final_data,
        "last_updated": new_timestamp
    }
    
    if not final_has_data and dev_data is not None:
        leaderboard_data[str(DEV_PHASE)] = dev_data
    
    os.makedirs('data', exist_ok=True)
    
    with open(DATA_FILE, 'w') as f:
        json.dump(leaderboard_data, f, indent=2)
        
    print("Successfully updated data/leaderboard.json")

if __name__ == "__main__":
    main()
