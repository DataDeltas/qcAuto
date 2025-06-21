import httpx
import requests
import base64
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
import pickle

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "lisan0007/lisanAtQA"
CHECKER_IDS_FILE = "ApprovedCheckerIDs.txt"
PROGRESS_FILE = "approval_progress.json"
COOKIE_FILE = "session_cookies.pkl"
LOGIN_URL = "https://roobtech.com/Account/Login"
LOGIN_DATA = {
    "Email": "lisunsarker@gmail.com",
    "Password": "Leasan@696985",
    "RememberMe": "true"
}
BALUR_CHAR_TZ = timezone(timedelta(hours=6))
ID_CHECK_INTERVAL = 300
IDS_PER_REQUEST = 3

class GitHubHandler:
    def __init__(self, token, repo):
        if not token:
            print("ERROR: GITHUB_TOKEN environment variable not set")
            sys.exit(1)
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = f"https://api.github.com/repos/{repo}/contents"
        self.last_id_check = 0

    def read_file(self, file_path):
        try:
            print(f"Reading file: {file_path}")
            response = requests.get(f"{self.base_url}/{file_path}", headers=self.headers, timeout=30)
            
            if response.status_code == 403:
                rate_limit = response.headers.get('X-RateLimit-Remaining', '0')
                print(f"Rate limit remaining: {rate_limit}")
                if int(rate_limit) < 10:
                    print("GitHub API rate limit nearly exhausted. Exiting.")
                    sys.exit(1)
                    
            if response.status_code == 404:
                print(f"File {file_path} not found")
                return None
                
            response.raise_for_status()
            content = response.json()
            decoded_content = base64.b64decode(content['content']).decode('utf-8')
            print(f"Successfully read {file_path}")
            return decoded_content
            
        except requests.exceptions.RequestException as e:
            print(f"Error reading {file_path}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error reading {file_path}: {e}")
            return None

    def get_file_sha(self, file_path):
        """Get the SHA of a file for updating"""
        try:
            response = requests.get(f"{self.base_url}/{file_path}", headers=self.headers, timeout=30)
            if response.status_code == 200:
                return response.json().get("sha")
            return None
        except Exception as e:
            print(f"Error getting SHA for {file_path}: {e}")
            return None

    def write_file(self, file_path, content, commit_message, sha=None):
        try:
            print(f"Writing file: {file_path}")
            params = {
                "message": commit_message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": "main"
            }
            if sha:
                params["sha"] = sha
                
            response = requests.put(f"{self.base_url}/{file_path}", 
                                  headers=self.headers, 
                                  json=params, 
                                  timeout=30)
            
            if response.status_code == 403:
                rate_limit = response.headers.get('X-RateLimit-Remaining', '0')
                print(f"Rate limit remaining: {rate_limit}")
                if int(rate_limit) < 10:
                    print("GitHub API rate limit nearly exhausted. Exiting.")
                    sys.exit(1)
                    
            response.raise_for_status()
            new_sha = response.json().get("content", {}).get("sha")
            print(f"Successfully wrote {file_path}")
            return new_sha
            
        except requests.exceptions.RequestException as e:
            print(f"Error writing {file_path}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error writing {file_path}: {e}")
            return None

    def get_checker_ids(self):
        content = self.read_file(CHECKER_IDS_FILE)
        if content:
            ids = {line.strip() for line in content.splitlines() if line.strip()}
            print(f"Found {len(ids)} checker IDs")
            return ids
        print("No checker IDs found")
        return set()

    def get_progress(self):
        content = self.read_file(PROGRESS_FILE)
        if content:
            try:
                progress = json.loads(content)
                completed_count = len(progress.get("completed_checkers", []))
                print(f"Found {completed_count} completed checkers")
                return progress
            except json.JSONDecodeError as e:
                print(f"Error parsing progress JSON: {e}")
                return {"completed_checkers": []}
        print("No progress file found, starting fresh")
        return {"completed_checkers": []}

    def save_progress(self, progress_data):
        try:
            content = json.dumps(progress_data, indent=4)
            sha = self.get_file_sha(PROGRESS_FILE)
            commit_message = f"Update progress - {len(progress_data['completed_checkers'])} completed - {datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
            result = self.write_file(PROGRESS_FILE, content, commit_message, sha)
            if result:
                print("Progress saved successfully")
                return True
            else:
                print("Failed to save progress")
                return False
        except Exception as e:
            print(f"Error in save_progress: {e}")
            return False

    def check_ids_available(self):
        if time.time() - self.last_id_check < ID_CHECK_INTERVAL:
            return True
        self.last_id_check = time.time()
        
        checker_ids = self.get_checker_ids()
        progress = self.get_progress()
        remaining = [id for id in checker_ids if id not in progress["completed_checkers"]]
        
        print(f"Total IDs: {len(checker_ids)}, Completed: {len(progress['completed_checkers'])}, Remaining: {len(remaining)}")
        return len(remaining) > 0

def load_cookies():
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'rb') as f:
                cookies = pickle.load(f)
                print("Loaded existing cookies")
                return cookies
        print("No existing cookies found")
    except Exception as e:
        print(f"Error loading cookies: {e}")
    return None

def save_cookies(cookies):
    try:
        # Check if cookies have changed before saving
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE, 'rb') as f:
                    existing = pickle.load(f)
                if existing == cookies:
                    print("Cookies unchanged, not saving")
                    return
            except:
                pass  # If we can't read existing, just save new ones
                
        with open(COOKIE_FILE, 'wb') as f:
            pickle.dump(cookies, f)
        print("Cookies saved successfully")
    except Exception as e:
        print(f"Error saving cookies: {e}")

def login():
    try:
        print("Attempting login...")
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            # Get login page first
            login_page = client.get(LOGIN_URL)
            print(f"Login page status: {login_page.status_code}")
            
            # Attempt login
            response = client.post(LOGIN_URL, data=LOGIN_DATA, headers=headers)
            print(f"Login response status: {response.status_code}")
            print(f"Login response URL: {response.url}")
            
            if response.status_code == 200 and "Login" not in str(response.url):
                print("Login successful")
                save_cookies(dict(client.cookies))
                return dict(client.cookies)
            else:
                print(f"Login failed - redirected to: {response.url}")
                return None
                
    except httpx.RequestError as e:
        print(f"Login request error: {e}")
        return None
    except Exception as e:
        print(f"Login unexpected error: {e}")
        return None

def approve_annotation(checker_ids, client):
    url = "https://roobtech.com/ProjectAnnotationAnalysis/ApproveAnnotation"
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest"
    }
    
    data = {"checkerIds": ",".join(checker_ids), "type": "post"}
    print(f"Attempting to approve {len(checker_ids)} annotations: {checker_ids}")
    
    try:
        response = client.post(url, data=data, headers=headers, timeout=30.0)
        print(f"Batch approval response status: {response.status_code}")
        
        if "Login" in str(response.url):
            print("Session expired during batch approval")
            return False
            
        response.raise_for_status()
        print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Successfully processed batch: {checker_ids}")
        return True
        
    except httpx.HTTPStatusError as e:
        print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Batch error {e.response.status_code}: {e}")
        print("Trying individual approvals...")
        
        # Try individual approvals
        success_count = 0
        for checker_id in checker_ids:
            data = {"checkerId": checker_id, "type": "post"}
            try:
                response = client.post(url, data=data, headers=headers, timeout=30.0)
                if "Login" in str(response.url):
                    print("Session expired during individual approval")
                    return False
                    
                response.raise_for_status()
                print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Processed individual: {checker_id}")
                success_count += 1
                
            except httpx.HTTPStatusError as e:
                print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Error processing {checker_id}: {e.response.status_code}")
            except Exception as e:
                print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Unexpected error processing {checker_id}: {e}")
                
        return success_count > 0
        
    except Exception as e:
        print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Unexpected batch error: {e}")
        return False

def main():
    try:
        print(f"Starting checker script at {datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
        
        github_handler = GitHubHandler(GITHUB_TOKEN, GITHUB_REPO)
        current_time = datetime.now(BALUR_CHAR_TZ)
        
        # Check operating hours (commented out the restrictive time check)
        # end_time = current_time.replace(hour=5, minute=38, second=0, microsecond=0)
        # if current_time.hour < 0 or (current_time.hour == 5 and current_time.minute > 38):
        #     print("Outside operating hours. Exiting.")
        #     return

        if not github_handler.check_ids_available():
            print("No checker IDs available. Exiting.")
            return

        # Load or get new cookies
        cookies = load_cookies()
        if not cookies:
            cookies = login()
            if not cookies:
                print("Failed to login. Exiting.")
                sys.exit(1)

        # Create HTTP client with cookies
        with httpx.Client(cookies=cookies, timeout=30.0, follow_redirects=True) as client:
            checker_ids = github_handler.get_checker_ids()
            progress = github_handler.get_progress()
            remaining_ids = [id for id in checker_ids if id not in progress["completed_checkers"]]
            
            if not remaining_ids:
                print("No checker IDs to process. Exiting.")
                return

            # Calculate batch size (simplified logic)
            # runs_left = max(1, ((5 * 60 + 38) // 2) - ((current_time.hour * 60 + current_time.minute - 1) // 2))
            # ids_needed = max(1, (400 - len(progress["completed_checkers"])) // runs_left)
            # batch_ids = remaining_ids[:min(ids_needed, IDS_PER_REQUEST)]
            
            # Simplified: just take up to IDS_PER_REQUEST
            batch_ids = remaining_ids[:IDS_PER_REQUEST]
            
            print(f"Processing batch of {len(batch_ids)} IDs: {batch_ids}")

            # Try to approve annotations
            if not approve_annotation(batch_ids, client):
                print("First attempt failed, trying to re-login...")
                cookies = login()
                if not cookies:
                    print("Re-login failed. Exiting.")
                    sys.exit(1)
                    
                # Update client cookies
                client.cookies.clear()
                client.cookies.update(cookies)
                
                if not approve_annotation(batch_ids, client):
                    print(f"Failed to process {batch_ids} after re-login. Exiting.")
                    sys.exit(1)

            # Update progress
            for checker_id in batch_ids:
                if checker_id not in progress["completed_checkers"]:
                    progress["completed_checkers"].append(checker_id)
            
            if github_handler.save_progress(progress):
                print(f"Successfully completed processing. Total completed: {len(progress['completed_checkers'])}")
            else:
                print("Warning: Failed to save progress to GitHub")
                
        print("Script completed successfully")
        
    except Exception as e:
        print(f"Unexpected error in main: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
