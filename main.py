#!/usr/bin/env python3

from e2b import FileType
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from typing import Optional
import tempfile
import os

from github_utils import (
    parse_repo_url,
    clone_repository,
    create_issue,
    create_branch,
    commit_and_push_changes,
    create_pull_request,
    get_repository
)
from build_mvp_website import (
    generate_website_in_sandbox,
    run_website_in_sandbox,
    stop_website_server,
    check_sandbox_logs
)

# Define request model
class WebsiteRequest(BaseModel):
    repo_url: str
    website_description: str
    public_access: Optional[bool] = False

# Initialize FastAPI app
app = FastAPI(title="Website Builder API")

@app.post("/build_website")
async def api_build_website(request: WebsiteRequest):
    """API endpoint to build an MVP website from GitHub repo and description."""
    try:
        return build_website(request.repo_url, request.website_description, request.public_access)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def download_files_from_sandbox(sandbox, remote_dir, local_dir):
    # List all entries in the current directory
    entries = sandbox.files.list(remote_dir)
    
    for entry in entries:
        # Get the path from the EntryInfo object
        file_path = entry.path  # Using path attribute of EntryInfo object
        
        if entry.name.startswith('.'):
            continue

        if not file_path.startswith(remote_dir):
            continue
        
        # Handle both directories and files
        if entry.type == FileType.DIR:
            # Create the corresponding local directory
            relative_path = os.path.relpath(file_path, remote_dir)
            new_local_dir = os.path.join(local_dir, relative_path)
            os.makedirs(new_local_dir, exist_ok=True)
            # Recursively download files from this directory
            download_files_from_sandbox(sandbox, file_path, new_local_dir)
        else:
            print(f"Downloading file: {entry.name}")
            
            # Calculate the relative path and create proper local path
            relative_path = os.path.relpath(file_path, remote_dir)
            local_path = os.path.join(local_dir, relative_path)
            
            # Create directory if needed
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            try:
                # Download file content
                content = sandbox.files.read(file_path)
                with open(local_path, 'wb') as f:
                    # Write as binary to handle all file types
                    if isinstance(content, str):
                        f.write(content.encode('utf-8'))
                    else:
                        f.write(content)
            except Exception as e:
                print(f"Error downloading {file_path}: {e}")

def build_website(repo_url, website_description, public_access=False):
    """
    Main function to build an MVP website from a GitHub repo and description.
    
    Steps:
    1. Clone the repository
    2. Create an issue
    3. Create a new branch
    4. Generate website in sandbox
    5. Run website in sandbox
    6. Commit and push changes
    7. Create a pull request
    """
    try:
        # Parse the repository URL to get owner and repo name
        repo_full_name = parse_repo_url(repo_url)

        # Get the repository object from GitHub
        repo = get_repository(repo_full_name)

        # Create an issue
        issue_title = "Build MVP Website"
        issue_body = f"""
        # Build MVP Website

        ## Description
        {website_description}

        ## Requirements
        - Create a simple Flask app
        - Implement the website according to the description
        """

        issue = create_issue(repo, issue_title, issue_body)
        if not issue:
            return {"success": False, "message": "Failed to create issue"}

        # Create a new branch
        branch_name = f"feature/mvp-website-{issue.number}"
        
        # Generate website in sandbox
        sandbox = generate_website_in_sandbox(website_description)
        if not sandbox:
            return {"success": False, "message": "Failed to generate website"}
        
        # Run the website in sandbox
        website_info = run_website_in_sandbox(sandbox, public_access=public_access)
        if not website_info:
            return {"success": False, "message": "Failed to run website"}
        
        # Clone the repository to temporary directory and create branch
        with tempfile.TemporaryDirectory() as temp_dir:
            if not clone_repository(repo_url, temp_dir):
                stop_website_server(website_info)
                return {"success": False, "message": "Failed to clone repository"}
                
            if not create_branch(temp_dir, branch_name):
                stop_website_server(website_info)
                return {"success": False, "message": "Failed to create branch"}
            
            # Download files from sandbox to temp directory
            download_files_from_sandbox(sandbox, '/home/user', temp_dir)
            
            # Commit and push changes
            commit_message = f"Create MVP website for #{issue.number}"
            if not commit_and_push_changes(temp_dir, commit_message):
                stop_website_server(website_info)
                return {"success": False, "message": "Failed to commit and push changes"}

            # Create a pull request
            pr_title = f"Fixes #{issue.number}: {issue_title}"
            pr_body = f"""
            # MVP Website Implementation

            This pull request addresses issue #{issue.number}.

            ## Changes Made
            - Created basic Flask application structure
            - Implemented website according to the description

            ## Description
            {website_description}

            ## Hosted Website
            The website is hosted at: {website_info["url"]}
            """

            pull_request = create_pull_request(repo, branch_name, "main", pr_title, pr_body)
            if not pull_request:
                stop_website_server(website_info)
                return {"success": False, "message": "Failed to create pull request"}

        return {
            "success": True,
            "message": "Successfully created MVP website",
            "issue_url": issue.html_url,
            "pr_url": pull_request.html_url,
            "website_url": website_info["url"]
        }
    except Exception as e:
        print(f"Error building website: {e}")
        return {"success": False, "message": f"Error: {str(e)}"}



if __name__ == "__main__":
    # Run the FastAPI server using uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
curl -X POST "http://localhost:8000/build_website" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/sr33j/RealEstateFinder",
    "website_description": "A website to find real estate properties",
    "public_access": true
  }'
"""






