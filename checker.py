import httpx
import logging
import base64
import json
import os
from datetime import datetime, timezone, timedelta
import requests
import time

# Configure logging
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
LOGIN_URL = "https://roobtech.com/Account/Login"
APPROVE_URL = "https://roobtech.com/ProjectAnnotationAnalysis/ApproveAnnotation"
LOGIN_DATA = {
    "Email": os.getenv("LOGIN_EMAIL"),
    "Password": os.getenv("LOGIN_PASSWORD"),
    "RememberMe": "true"
}
BANGLADESH_TZ = timezone(timedelta(hours=6))

class GitHubHandler:
    def __init__(self):
        if not GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN environment variable not set")
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.base_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents"

    def read_file(self, file_path):
        try:
            response = requests.get(f"{self.base_url}/{file_path}", headers=self.headers)
            response.raise_for_status()
            content = response.json()
            return base64.b64decode(content['content']).decode('utf-8')
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")
            return None

    def get_file_sha(self, file_path):
        try:
            response = requests.get(f"{self.base_url}/{file_path}", headers=self.headers)
            if response.status_code == 200:
                return response.json().get("sha")
            return None
        except Exception as e:
            logger.error(f"Error getting SHA for {file_path}: {e}")
            return None

    def write_file(self, file_path, content, commit_message):
        try:
            sha = self.get_file_sha(file_path)
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
                json=params
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error writing {file_path}: {e}")
            return False

    def get_next_checker_id(self):
        try:
            # Read checker IDs
            content = self.read_file(CHECKER_IDS_FILE)
            if not content:
                logger.error("No checker IDs file found or file is empty")
                return None, None
            
            checker_ids = [line.strip() for line in content.splitlines() if line.strip()]
            if not checker_ids:
                logger.error("No checker IDs found in file")
                return None, None
            
            # Read progress
            progress_content = self.read_file(PROGRESS_FILE)
            if progress_content:
                try:
                    progress = json.loads(progress_content)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in progress file")
                    progress = {"completed_checkers": []}
            else:
                progress = {"completed_checkers": []}
            
            completed_ids = set(progress.get("completed_checkers", []))
            
            # Find first uncompleted ID
            for checker_id in checker_ids:
                if checker_id not in completed_ids:
                    logger.info(f"Found next checker ID to process: {checker_id}")
                    return checker_id, progress
            
            logger.info("All checker IDs have been processed")
            return None, None
            
        except Exception as e:
            logger.error(f"Error getting next checker ID: {e}")
            return None, None

    def save_progress(self, checker_id, progress):
        try:
            if checker_id not in progress["completed_checkers"]:
                progress["completed_checkers"].append(checker_id)
                progress["last_updated"] = datetime.now(BANGLADESH_TZ).isoformat()
                
                content = json.dumps(progress, indent=4)
                commit_message = f"Update progress - Completed {checker_id} at {datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                
                if self.write_file(PROGRESS_FILE, content, commit_message):
                    logger.info(f"Progress saved for checker ID: {checker_id}")
                    return True
                else:
                    logger.error(f"Failed to save progress for checker ID: {checker_id}")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error saving progress: {e}")
            return False

def login():
    try:
        logger.info("Attempting login...")
        client = httpx.Client(follow_redirects=True, timeout=30.0)
        
        # Get login page first
        login_page = client.get(LOGIN_URL)
        logger.info(f"Login page status: {login_page.status_code}")
        
        # Attempt login
        response = client.post(LOGIN_URL, data=LOGIN_DATA)
        logger.info(f"Login response status: {response.status_code}")
        
        if response.status_code == 200 and "Login" not in str(response.url):
            logger.info("Login successful")
            return client
        else:
            logger.error(f"Login failed - redirected to: {response.url}")
            client.close()
            return None
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        return None

def approve_annotation(client, checker_id):
    try:
        headers = {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest"
        }
        
        data = {"checkerId": checker_id, "type": "post"}
        
        response = client.post(APPROVE_URL, data=data, headers=headers)
        logger.info(f"Approval response status: {response.status_code}")
        
        if "Login" in str(response.url):
            logger.error("Session expired")
            return False
            
        response.raise_for_status()
        logger.info(f"Successfully approved checker ID: {checker_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error approving checker ID {checker_id}: {e}")
        return False

def main():
    try:
        logger.info(f"Starting approval script at {datetime.now(BANGLADESH_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Initialize GitHub handler
        github = GitHubHandler()
        
        # Get next checker ID
        checker_id, progress = github.get_next_checker_id()
        if not checker_id:
            logger.info("No more checker IDs to process")
            return
            
        logger.info(f"Processing checker ID: {checker_id}")
        
        # Login
        client = login()
        if not client:
            logger.error("Failed to login. Exiting.")
            return
        
        try:
            # Approve annotation
            if approve_annotation(client, checker_id):
                # Save progress
                if github.save_progress(checker_id, progress):
                    logger.info(f"Successfully processed and saved progress for checker ID: {checker_id}")
                else:
                    logger.error(f"Failed to save progress for checker ID: {checker_id}")
            else:
                logger.error(f"Failed to approve checker ID: {checker_id}")
        finally:
            client.close()
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()
