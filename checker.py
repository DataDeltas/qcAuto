import httpx
import requests
import base64
import json
import time
import os
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
            response = requests.get(f"{self.base_url}/{file_path}", headers=self.headers)
            if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                print("GitHub API rate limit nearly exhausted. Exiting.")
                exit(1)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            content = response.json()
            return base64.b64decode(content['content']).decode('utf-8')
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return None

    def write_file(self, file_path, content, commit_message, sha=None):
        try:
            params = {
                "message": commit_message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": "main"
            }
            if sha:
                params["sha"] = sha
            response = requests.put(f"{self.base_url}/{file_path}", headers=self.headers, json=params)
            if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                print("GitHub API rate limit nearly exhausted. Exiting.")
                exit(1)
            response.raise_for_status()
            return response.json().get("content", {}).get("sha")
        except Exception as e:
            print(f"Error writing {file_path}: {e}")
            return None

    def get_checker_ids(self):
        content = self.read_file(CHECKER_IDS_FILE)
        return {line.strip() for line in content.splitlines() if line.strip()} if content else set()

    def get_progress(self):
        content = self.read_file(PROGRESS_FILE)
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"completed_checkers": []}
        return {"completed_checkers": []}

    def save_progress(self, progress_data):
        content = json.dumps(progress_data, indent=4)
        sha = self.read_file(PROGRESS_FILE)
        if sha:
            sha = json.loads(requests.get(f"{self.base_url}/{PROGRESS_FILE}", headers=self.headers).text).get("sha")
        return self.write_file(PROGRESS_FILE, content, f"Update progress {datetime.now().isoformat()}", sha)

    def check_ids_available(self):
        if time.time() - self.last_id_check < ID_CHECK_INTERVAL:
            return True
        self.last_id_check = time.time()
        checker_ids = self.get_checker_ids()
        progress = self.get_progress()
        return bool([id for id in checker_ids if id not in progress["completed_checkers"]])

def load_cookies():
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'rb') as f:
                return pickle.load(f)
    except Exception as e:
        print(f"Error loading cookies: {e}")
    return None

def save_cookies(cookies):
    try:
        if os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'rb') as f:
                existing = pickle.load(f)
            if existing == cookies:
                return
        with open(COOKIE_FILE, 'wb') as f:
            pickle.dump(cookies, f)
    except Exception as e:
        print(f"Error saving cookies: {e}")

def login():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        with httpx.Client(follow_redirects=True) as client:
            client.get(LOGIN_URL)
            response = client.post(LOGIN_URL, data=LOGIN_DATA, headers=headers)
            if response.status_code == 200 and "Login" not in response.url.path:
                print("Login successful")
                save_cookies(client.cookies)
                return client.cookies
            print("Login failed")
            return None
    except httpx.HTTPError as e:
        print(f"Login error: {e}")
        return None

def approve_annotation(checker_ids, client):
    url = "https://roobtech.com/ProjectAnnotationAnalysis/ApproveAnnotation"
    headers = {
        "accept": "*/*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    }
    data = {"checkerIds": ",".join(checker_ids), "type": "post"}
    try:
        response = client.post(url, data=data, headers=headers, timeout=10.0)
        if "Login" in response.url.path:
            print("Session expired")
            return False
        response.raise_for_status()
        print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Processed {checker_ids}")
        return True
    except httpx.HTTPError as e:
        print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Batch error: {e}")
        for checker_id in checker_ids:
            data = {"checkerId": checker_id, "type": "post"}
            try:
                response = client.post(url, data=data, headers=headers, timeout=10.0)
                if "Login" in response.url.path:
                    print("Session expired")
                    return False
                response.raise_for_status()
                print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Processed {checker_id}")
            except httpx.HTTPError as e:
                print(f"[{datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}] Error processing {checker_id}: {e}")
                return False
        return True

def main():
    github_handler = GitHubHandler(GITHUB_TOKEN, GITHUB_REPO)
    current_time = datetime.now(BALUR_CHAR_TZ)
    end_time = current_time.replace(hour=5, minute=38, second=0, microsecond=0)
    if current_time.hour < 0 or (current_time.hour == 5 and current_time.minute > 38):
        print("Outside operating hours. Exiting.")
        return
    if not github_handler.check_ids_available():
        print("No checker IDs available. Exiting.")
        return
    cookies = load_cookies()
    if not cookies:
        cookies = login()
        if not cookies:
            print("Failed to login. Exiting.")
            return
    with httpx.Client(cookies=cookies, timeout=10.0, follow_redirects=True) as client:
        checker_ids = github_handler.get_checker_ids()
        progress = github_handler.get_progress()
        remaining_ids = [id for id in checker_ids if id not in progress["completed_checkers"]]
        if not remaining_ids:
            print("No checker IDs to process. Exiting.")
            return
        runs_left = max(1, ((5 * 60 + 38) // 2) - ((current_time.hour * 60 + current_time.minute - 1) // 2))
        ids_needed = max(1, (400 - len(progress["completed_checkers"])) // runs_left)
        batch_ids = remaining_ids[:min(ids_needed, IDS_PER_REQUEST)]
        if not approve_annotation(batch_ids, client):
            cookies = login()
            if not cookies:
                print("Re-login failed. Exiting.")
                return
            client.cookies.update(cookies)
            if not approve_annotation(batch_ids, client):
                print(f"Failed to process {batch_ids} after re-login. Exiting.")
                return
        for checker_id in batch_ids:
            progress["completed_checkers"].append(checker_id)
        github_handler.save_progress(progress)

if __name__ == "__main__":
    main()
