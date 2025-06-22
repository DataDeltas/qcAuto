import httpx
import requests
import base64
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta
import pickle
import random
import logging
from typing import Optional, Dict, Set, List

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "lisan0007/lisanAtQA"
CHECKER_IDS_FILE = "ApprovedCheckerIDs.txt"
PROGRESS_FILE = "approval_progress.json"
COOKIE_FILE = "session_cookies.pkl"
LOGIN_URL = "https://roobtech.com/Account/Login"
LOGIN_DATA = {
    "Email": os.getenv("LOGIN_EMAIL", "lisunsarker@gmail.com"),
    "Password": os.getenv("LOGIN_PASSWORD", "Leasan@696985"),
    "RememberMe": "true"
}
BALUR_CHAR_TZ = timezone(timedelta(hours=6))
ID_CHECK_INTERVAL = 120  # Reduced to 2 minutes
IDS_PER_REQUEST = 3
MAX_RETRIES = 3
RETRY_DELAY = 5

class RateLimitError(Exception):
    pass

class SessionExpiredError(Exception):
    pass

class GitHubHandler:
    def __init__(self, token: str, repo: str):
        if not token:
            logger.error("GITHUB_TOKEN environment variable not set")
            sys.exit(1)
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = f"https://api.github.com/repos/{repo}/contents"
        self.last_id_check = 0
        self.rate_limit_remaining = None

    def check_rate_limit(self, response: requests.Response) -> None:
        self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', '0'))
        if self.rate_limit_remaining < 10:
            logger.warning(f"GitHub API rate limit low: {self.rate_limit_remaining} remaining")
            if self.rate_limit_remaining == 0:
                reset_time = int(response.headers.get('X-RateLimit-Reset', '0'))
                wait_time = max(reset_time - time.time(), 0)
                raise RateLimitError(f"Rate limit exceeded. Reset in {wait_time:.0f} seconds")

    def read_file(self, file_path: str, retries: int = MAX_RETRIES) -> Optional[str]:
        for attempt in range(retries):
            try:
                logger.info(f"Reading file: {file_path} (attempt {attempt + 1}/{retries})")
                response = requests.get(
                    f"{self.base_url}/{file_path}", 
                    headers=self.headers, 
                    timeout=30
                )
                
                self.check_rate_limit(response)
                
                if response.status_code == 404:
                    logger.warning(f"File {file_path} not found")
                    return None
                    
                response.raise_for_status()
                content = response.json()
                decoded_content = base64.b64decode(content['content']).decode('utf-8')
                logger.info(f"Successfully read {file_path}")
                return decoded_content
                
            except RateLimitError as e:
                logger.error(str(e))
                raise
            except Exception as e:
                logger.error(f"Error reading {file_path} (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise
        return None

    def write_file(self, file_path: str, content: str, commit_message: str, 
                   sha: Optional[str] = None, retries: int = MAX_RETRIES) -> Optional[str]:
        for attempt in range(retries):
            try:
                logger.info(f"Writing file: {file_path} (attempt {attempt + 1}/{retries})")
                params = {
                    "message": commit_message,
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": "main"
                }
                if sha:
                    params["sha"] = sha
                    
                response = requests.put(
                    f"{self.base_url}/{file_path}", 
                    headers=self.headers, 
                    json=params, 
                    timeout=30
                )
                
                self.check_rate_limit(response)
                response.raise_for_status()
                
                new_sha = response.json().get("content", {}).get("sha")
                logger.info(f"Successfully wrote {file_path}")
                return new_sha
                
            except RateLimitError as e:
                logger.error(str(e))
                raise
            except Exception as e:
                logger.error(f"Error writing {file_path} (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise
        return None

    def get_checker_ids(self) -> Set[str]:
        content = self.read_file(CHECKER_IDS_FILE)
        if content:
            ids = {line.strip() for line in content.splitlines() if line.strip()}
            logger.info(f"Found {len(ids)} checker IDs")
            return ids
        logger.warning("No checker IDs found")
        return set()

    def get_progress(self) -> Dict:
        content = self.read_file(PROGRESS_FILE)
        if content:
            try:
                progress = json.loads(content)
                completed_count = len(progress.get("completed_checkers", []))
                logger.info(f"Found {completed_count} completed checkers")
                return progress
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing progress JSON: {e}")
                return {"completed_checkers": []}
        logger.info("No progress file found, starting fresh")
        return {"completed_checkers": []}

    def save_progress(self, progress_data: Dict) -> bool:
        try:
            # Add timestamp to progress data
            progress_data['last_updated'] = datetime.now(BALUR_CHAR_TZ).isoformat()
            content = json.dumps(progress_data, indent=4)
            sha = self.get_file_sha(PROGRESS_FILE)
            
            # Add random component to avoid conflicts
            random_suffix = ''.join(random.choices('0123456789', k=4))
            commit_message = (f"Update progress - {len(progress_data['completed_checkers'])} "
                            f"completed - {datetime.now(BALUR_CHAR_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                            f" ({random_suffix})")
            
            result = self.write_file(PROGRESS_FILE, content, commit_message, sha)
            if result:
                logger.info("Progress saved successfully")
                return True
            logger.error("Failed to save progress")
            return False
        except Exception as e:
            logger.error(f"Error in save_progress: {e}")
            return False

def create_http_client(cookies: Optional[Dict] = None) -> httpx.Client:
    return httpx.Client(
        cookies=cookies,
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
    )

def login(retries: int = MAX_RETRIES) -> Optional[Dict]:
    for attempt in range(retries):
        try:
            logger.info(f"Attempting login (attempt {attempt + 1}/{retries})")
            with create_http_client() as client:
                # Get login page first
                login_page = client.get(LOGIN_URL)
                logger.info(f"Login page status: {login_page.status_code}")
                
                # Attempt login
                response = client.post(LOGIN_URL, data=LOGIN_DATA)
                logger.info(f"Login response status: {response.status_code}")
                
                if response.status_code == 200 and "Login" not in str(response.url):
                    logger.info("Login successful")
                    return dict(client.cookies)
                logger.warning(f"Login failed - redirected to: {response.url}")
                
        except Exception as e:
            logger.error(f"Login error (attempt {attempt + 1}): {e}")
            if attempt < retries - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
    return None

def main():
    try:
        # Add random delay to avoid exact timing
        random_delay = random.uniform(0, 30)
        logger.info(f"Starting with random delay of {random_delay:.2f} seconds")
        time.sleep(random_delay)

        current_time = datetime.now(BALUR_CHAR_TZ)
        logger.info(f"Starting checker script at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

        github_handler = GitHubHandler(GITHUB_TOKEN, GITHUB_REPO)
        
        if not github_handler.check_ids_available():
            logger.info("No checker IDs available. Exiting.")
            return

        # Login and process
        cookies = login()
        if not cookies:
            logger.error("Failed to login. Exiting.")
            sys.exit(1)

        with create_http_client(cookies) as client:
            process_checker_ids(github_handler, client)

        logger.info("Script completed successfully")

    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
