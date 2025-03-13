import os
from github import Github, GithubException
from dotenv import load_dotenv
import re
import subprocess
import time

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

def fork_repository(repo):
    """Fork the repository to the authenticated user's account."""
    try:
        # Get the authenticated user
        user = github_client.get_user()
        
        # Check if a fork already exists
        for fork in repo.get_forks():
            if fork.owner.login == user.login:
                print(f"Using existing fork: {fork.html_url}")
                return fork
        
        # Create a new fork
        fork = user.create_fork(repo)
        print(f"Repository forked: {fork.html_url}")
        
        # Give GitHub some time to complete the fork
        time.sleep(5)
        
        return fork
    except GithubException as e:
        print(f"Error forking repository: {e}")
        return None

def clone_repository(repo_url, local_path, use_fork=True):
    """Clone the repository to a local directory."""
    try:
        # If use_fork is True, fork the repository first and clone the fork instead
        if use_fork:
            repo_full_name = parse_repo_url(repo_url)
            original_repo = get_repository(repo_full_name)
            forked_repo = fork_repository(original_repo)
            
            if forked_repo:
                # Use the forked repo URL
                repo_url = forked_repo.clone_url
                print(f"Using forked repository: {repo_url}")
            else:
                print("Failed to fork repository, falling back to original repo")
        
        # Include token in the URL for authentication
        if GITHUB_TOKEN and "https://github.com" in repo_url:
            auth_repo_url = repo_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")
        else:
            auth_repo_url = repo_url
            
        subprocess.run(["git", "clone", auth_repo_url, local_path], check=True)
        print(f"Repository cloned to {local_path}")
        
        # Configure Git to use the token for subsequent operations
        subprocess.run(["git", "-C", local_path, "config", "user.name", "DeployBot"], check=True)
        subprocess.run(["git", "-C", local_path, "config", "user.email", "deploybot@example.com"], check=True)
        
        if use_fork:
            # Add the original repository as a remote called "upstream"
            subprocess.run(["git", "-C", local_path, "remote", "add", "upstream", repo_url.replace("https://github.com", f"https://{GITHUB_TOKEN}@github.com")], check=True)
            
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
        # Get the authenticated user to determine the head branch name
        user = github_client.get_user()
        
        # Format the head branch as username:branch_name
        head = f"{user.login}:{branch_name}"
        
        pull_request = repo.create_pull(
            title=title,
            body=body,
            head=head,
            base=base_branch
        )
        print(f"Pull request created: {pull_request.html_url}")
        return pull_request
    except GithubException as e:
        print(f"Error creating pull request: {e}")
        return None
