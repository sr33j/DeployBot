import os
from github import Github, GithubException
from dotenv import load_dotenv
import re
import subprocess

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Initialize clients
github_client = Github(GITHUB_TOKEN)

def parse_repo_url(repo_url):
    """Extract owner and repo name from GitHub URL."""
    pattern = r"https?://github\.com/([^/]+)/([^/]+)"
    match = re.match(pattern, repo_url)
    if match:
        owner, repo_name = match.groups()
        return f"{owner}/{repo_name}"
    else:
        raise ValueError(f"Invalid GitHub repository URL: {repo_url}")

def get_repository(repo_full_name):
    """Get a repository object from GitHub."""
    return github_client.get_repo(repo_full_name)

def clone_repository(repo_url, local_path):
    """Clone the repository to a local directory."""
    try:
        # Include token in the URL for authentication
        if GITHUB_TOKEN and "https://github.com" in repo_url:
            auth_repo_url = repo_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")
        else:
            auth_repo_url = repo_url
            
        subprocess.run(["git", "clone", auth_repo_url, local_path], check=True)
        print(f"Repository cloned to {local_path}")
        
        # Configure Git to use the token for subsequent operations
        subprocess.run(["git", "-C", local_path, "config", "user.name", "GitHub Actions"], check=True)
        subprocess.run(["git", "-C", local_path, "config", "user.email", "actions@github.com"], check=True)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error cloning repository: {e}")
        return False

def create_issue(repo, title, description):
    """Create an issue in the repository."""
    try:
        issue = repo.create_issue(title=title, body=description)
        print(f"Issue created: {issue.html_url}")
        return issue
    except GithubException as e:
        print(f"Error creating issue: {e}")
        return None

def create_branch(local_path, branch_name, base_branch="main"):
    """Create a new branch from the base branch."""
    try:
        # Make sure we're on the base branch and it's up to date
        subprocess.run(["git", "-C", local_path, "checkout", base_branch], check=True)
        subprocess.run(["git", "-C", local_path, "pull"], check=True)

        # Create and checkout new branch
        subprocess.run(["git", "-C", local_path, "checkout", "-b", branch_name], check=True)
        print(f"Created and checked out branch: {branch_name}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error creating branch: {e}")
        return False



def commit_and_push_changes(local_path, commit_message):
    """Commit and push changes to the remote repository."""
    try:
        # Stage all changes
        subprocess.run(["git", "-C", local_path, "add", "."], check=True)

        # Commit changes without GPG signing
        subprocess.run(["git", "-C", local_path, "commit", "--no-gpg-sign", "-m", commit_message], check=True)

        # Push changes to remote
        subprocess.run(["git", "-C", local_path, "push", "--set-upstream", "origin", "HEAD"], check=True)

        print(f"Changes committed and pushed with message: {commit_message}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error committing and pushing changes: {e}")
        return False

def create_pull_request(repo, branch_name, base_branch, title, body):
    """Create a pull request from the branch to the base branch."""
    try:
        pull_request = repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch
        )
        print(f"Pull request created: {pull_request.html_url}")
        return pull_request
    except GithubException as e:
        print(f"Error creating pull request: {e}")
        return None
