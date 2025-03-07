import os
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional
import json
from e2b_code_interpreter import Sandbox

load_dotenv()

# Configure API keys and tokens
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

class FileDescription(BaseModel):
    file_name: str
    description: str
    importance: Optional[int] = None  # For ranking files by importance

def define_website_structure(website_description):
    """Use OpenAI to define the file structure for the website based on description."""
    try:
        system_prompt = {"role": "system", "content": "You are a helpful assistant."}
        message_list = [system_prompt]
        
        user_prompt = f"""
        Please write the simplest flask app that will meet the requirements of the following description:
        {website_description}

        Output the directory structure of the app. It should be a list of files and a description of the contents of each file.
        EXAMPLE:
        [
        {{
            "file_name": "app.py",
            "description": "This is the main file that will run the app."
        }},
        {{
            "file_name": "requirements.txt", 
            "description": "This is the requirements file for the app."
        }},
        {{
            "file_name": "README.md",
            "description": "This is the README file for the app."
        }},
        {{
            "file_name": "templates/index.html",
            "description": "This is the template for the index page of the app."
        }},
        {{
            "file_name": "static/style.css",
            "description": "This is the CSS file for the app."
        }},
        {{
            "file_name": "static/script.js",
            "description": "This is the JavaScript file for the app."
        }}
        ]

        Do not include any other text. Do not include any markdown, code blocks, or explanations.
        OUTPUT:
        """
        
        message_list.append({"role": "user", "content": user_prompt})
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=message_list
        )
        
        structure_content = completion.choices[0].message.content
        
        # Parse the JSON output
        file_structures = json.loads(structure_content)
        
        # Convert to Pydantic models
        file_descriptions = [FileDescription(**file) for file in file_structures]
        
        # Ensure app.py and requirements.txt exist
        essential_files = ["app.py", "requirements.txt"]
        for essential_file in essential_files:
            if not any(file.file_name == essential_file for file in file_descriptions):
                file_descriptions.append(
                    FileDescription(
                        file_name=essential_file,
                        description=f"This is the {essential_file} file for the app."
                    )
                )
        
        # Have LLM rank files by importance
        message_list.append({"role": "assistant", "content": structure_content})
        
        rank_prompt = f"""
        Please rank the following files by importance, with 1 being the most important.
        Output the result as a JSON list with the file name and its rank:
        {structure_content}
        
        Example output:
        [
        {{
            "file_name": "app.py",
            "importance": 1
        }},
        {{
            "file_name": "requirements.txt",
            "importance": 2
        }}
        ]
        
        Do not include any other text. Do not include any markdown, code blocks, or explanations.
        """
        
        message_list.append({"role": "user", "content": rank_prompt})
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=message_list
        )
        
        ranking_content = completion.choices[0].message.content
        rankings = json.loads(ranking_content)
        
        # Update importance in file descriptions
        rank_map = {item["file_name"]: item["importance"] for item in rankings}
        for file in file_descriptions:
            if file.file_name in rank_map:
                file.importance = rank_map[file.file_name]
        
        # Sort file descriptions by importance
        file_descriptions.sort(key=lambda x: x.importance if x.importance is not None else 999)
        
        print(f"Defined website structure with {len(file_descriptions)} files")
        return file_descriptions
    except Exception as e:
        print(f"Error defining website structure: {e}")
        return None

def generate_file_content(file_description, website_description):
    """Generate content for a single file using OpenAI."""
    try:
        system_prompt = {"role": "system", "content": "You are a helpful assistant. Generate only code without explanations, markdown, or backticks."}
        message_list = [system_prompt]
        
        # Add special handling for requirements.txt
        if file_description.file_name == "requirements.txt":
            user_prompt = f"""
            Please write the file {file_description.file_name} with the following description:
            {file_description.description}
            
            The website description is:
            {website_description}
            
            IMPORTANT CONSTRAINTS:
            1. Include only the absolute minimum required dependencies
            2. DO NOT include version numbers for any package
            3. Each dependency should be on its own line with no version constraints
            4. Include only well-established, widely-used packages
            
            Generate only the file content without any markdown, code blocks, explanations, or backticks.
            """
        else:
            user_prompt = f"""
            Please write the file {file_description.file_name} with the following description:
            {file_description.description}
            
            The website description is:
            {website_description}
            
            Generate only the file content without any markdown, code blocks, explanations, or backticks.
            """
        
        message_list.append({"role": "user", "content": user_prompt})
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=message_list
        )
        
        file_content = completion.choices[0].message.content
        print(f"Generated content for {file_description.file_name}")
        return file_content
    except Exception as e:
        print(f"Error generating content for {file_description.file_name}: {e}")
        return None

def generate_website_in_sandbox(website_description):
    """Generate website files and save them to an e2b sandbox."""
    try:
        # Define the website structure
        file_descriptions = define_website_structure(website_description)
        if not file_descriptions:
            return None
        
        # Create a sandbox
        sandbox = Sandbox()
        print(f"Created sandbox: {sandbox.sandbox_id}")
        
        # Generate and write each file
        for file_desc in file_descriptions:
            # Generate file content
            file_content = generate_file_content(file_desc, website_description)
            if not file_content:
                continue
            
            # Create directory structure in sandbox if needed
            dir_path = os.path.dirname(file_desc.file_name)
            if dir_path:
                sandbox.commands.run(f"mkdir -p /home/user/{dir_path}")
            
            # Write file to sandbox
            sandbox_path = f"/home/user/{file_desc.file_name}"
            sandbox.files.write(sandbox_path, file_content)
            print(f"Wrote {file_desc.file_name} to sandbox")
        
        print(f"Website generation completed in sandbox: {sandbox.sandbox_id}")
        return sandbox
    except Exception as e:
        print(f"Error generating website in sandbox: {e}")
        return None

def run_website_in_sandbox(sandbox, port=5000, public_access=False):
    """Run the generated website in the sandbox."""
    try:
        # Install requirements
        print("Installing requirements...")
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Try to install requirements
                result = sandbox.commands.run("cd /home/user && pip install -r requirements.txt")
                break  # If successful, exit the retry loop
            except Exception as e:
                error_message = str(e)
                print(f"Error installing requirements: {error_message}")
                retry_count += 1
                
                if retry_count >= max_retries:
                    print(f"Failed to install requirements after {max_retries} attempts")
                    raise
                
                print(f"Attempting to fix requirements.txt (attempt {retry_count}/{max_retries})")
                # Regenerate requirements.txt with error context
                file_desc = FileDescription(
                    file_name="requirements.txt",
                    description="Requirements file for the app"
                )
                fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                if fixed_content:
                    sandbox.files.write("/home/user/requirements.txt", fixed_content)
        
        # Start the server with similar retry logic
        if public_access:
            print("Setting up gunicorn server...")
            retry_count = 0
            while retry_count < max_retries:
                try:
                    sandbox.commands.run("pip install gunicorn")
                    process = sandbox.commands.run(
                        "cd /home/user && gunicorn --bind 0.0.0.0:5000 app:app", 
                        background=True
                    )
                    break
                except Exception as e:
                    error_message = str(e)
                    print(f"Error starting gunicorn server: {error_message}")
                    retry_count += 1
                    
                    if retry_count >= max_retries:
                        print(f"Failed to start server after {max_retries} attempts")
                        raise
                    
                    print(f"Attempting to fix app.py (attempt {retry_count}/{max_retries})")
                    # Regenerate app.py with error context
                    file_desc = FileDescription(
                        file_name="app.py",
                        description="Main application file"
                    )
                    fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                    if fixed_content:
                        sandbox.files.write("/home/user/app.py", fixed_content)
        else:
            print("Starting Flask development server...")
            retry_count = 0
            while retry_count < max_retries:
                try:
                    process = sandbox.commands.run(
                        "cd /home/user && python app.py", 
                        background=True
                    )
                    break
                except Exception as e:
                    error_message = str(e)
                    print(f"Error starting Flask server: {error_message}")
                    retry_count += 1
                    
                    if retry_count >= max_retries:
                        print(f"Failed to start server after {max_retries} attempts")
                        raise
                    
                    print(f"Attempting to fix app.py (attempt {retry_count}/{max_retries})")
                    # Regenerate app.py with error context
                    file_desc = FileDescription(
                        file_name="app.py",
                        description="Main application file"
                    )
                    fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                    if fixed_content:
                        sandbox.files.write("/home/user/app.py", fixed_content)
        
        # Get public URL
        host = sandbox.get_host(port)
        url = f"https://{host}"
        print(f"Website running at: {url}")
        
        return {
            "process": process,
            "url": url,
            "sandbox": sandbox
        }
    except Exception as e:
        print(f"Error running website in sandbox: {e}")
        return None

def regenerate_file_with_error(file_description, error_message, sandbox):
    """Regenerate a file's content with error context."""
    try:
        # Read the current file content to provide context
        current_content = ""
        try:
            current_content = sandbox.files.read(f"/home/user/{file_description.file_name}")
        except:
            pass  # File might not exist or be readable
            
        system_prompt = {"role": "system", "content": "You are a helpful assistant. Generate only code without explanations, markdown, or backticks."}
        message_list = [system_prompt]
        
        user_prompt = f"""
        The file {file_description.file_name} needs to be fixed. When trying to use it, the following error occurred:
        
        ERROR: {error_message}
        
        Current file content:
        {current_content}
        
        Please fix the file and provide the corrected version. Generate only the file content without any markdown, code blocks, explanations, or backticks.
        """
        
        message_list.append({"role": "user", "content": user_prompt})
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=message_list
        )
        
        fixed_content = completion.choices[0].message.content
        print(f"Regenerated content for {file_description.file_name} with error context")
        return fixed_content
    except Exception as e:
        print(f"Error regenerating content for {file_description.file_name}: {e}")
        return None

def stop_website_server(website_info):
    """Stop the running website server."""
    if website_info and "process" in website_info:
        website_info["process"].kill()
        print("Website server stopped")