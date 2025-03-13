import os
from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional
import json
from e2b_code_interpreter import Sandbox
import logging
import traceback
import sys
from datetime import datetime
from langsmith.wrappers import wrap_openai


load_dotenv()

# Configure API keys and tokens
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# client = OpenAI(api_key=OPENAI_API_KEY)
client = wrap_openai(OpenAI(api_key=OPENAI_API_KEY))

# Set up logging
log_directory = "logs"
os.makedirs(log_directory, exist_ok=True)
log_filename = os.path.join(log_directory, f"website_builder_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)

# Create logger for this module
logger = logging.getLogger('website_builder')

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
        Please write the simplest flask app that will meet the requirements of the following description.
        The website should be visually appealing and easy to use.
        DESCRIPTION:
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

def generate_file_content(file_description, website_description, message_list=None):
    """Generate content for a single file using OpenAI."""
    try:
        # If no message list is provided, create a new one
        if message_list is None:
            system_prompt = {
            "role": "system",
            "content": "You are a code generation assistant. ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary."
            }
            message_list = [system_prompt]
        
        # Add special handling for app.py to ensure it binds to all interfaces
        if file_description.file_name == "app.py":
            user_prompt = f"""
            Please write the file {file_description.file_name} with the following description:
            {file_description.description}
            
            The website description is:
            {website_description}
            
            IMPORTANT CONSTRAINTS:
            1. Make sure the Flask app is properly configured to run on all interfaces (0.0.0.0)
            2. Set debug=True during development
            3. Include error handlers for common HTTP errors
            4. Wrap route handlers in try/except blocks to prevent unhandled exceptions
            
            ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary.
            """
        # Add special handling for requirements.txt
        elif file_description.file_name == "requirements.txt":
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
            5. Ensure necessary dependencies are included for the app to run such as flask, gunicorn, etc.
            
            ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary.
            """
        else:
            user_prompt = f"""
            Please write the file {file_description.file_name} with the following description:
            {file_description.description}
            
            The website description is:
            {website_description}
            
            ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary.
            """
        
        # Use the existing message list and add the new user prompt
        message_list.append({"role": "user", "content": user_prompt})
        
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=message_list,
        )
        
        file_content = completion.choices[0].message.content
        logger.info(f"Generated content for {file_description.file_name}")
        
        # Return the file content
        return file_content
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error generating content for {file_description.file_name}: {str(e)}\n{error_details}")
        return None

def generate_website_in_sandbox(website_description):
    """Generate website files and save them to an e2b sandbox."""
    try:
        logger.info("Starting website generation in sandbox")
        # Define the website structure
        file_descriptions = define_website_structure(website_description)
        if not file_descriptions:
            logger.error("Failed to define website structure")
            return None
        
        # Create a sandbox
        sandbox = Sandbox(timeout=60*60)
        logger.info(f"Created sandbox: {sandbox.sandbox_id}")
        
        # Initialize the message list with system prompt and project structure
        system_prompt = {
        "role": "system",
        "content": "You are a code generation assistant. ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary."
        }
        message_list = [system_prompt]
        
        # Add file structure information to the message list
        file_structure_info = "Project structure:\n" + "\n".join([f"- {file.file_name}: {file.description}" for file in file_descriptions])
        message_list.append({"role": "user", "content": f"I'm building a web application with the following description:\n{website_description}\n\n{file_structure_info}"})
        message_list.append({"role": "assistant", "content": "I'll help you generate the code for each file in this project structure."})
        
        # Generate and write each file
        for file_desc in file_descriptions:
            # Generate file content
            logger.info(f"Generating content for {file_desc.file_name}")
            file_content = generate_file_content(file_desc, website_description, message_list)
            if not file_content:
                logger.warning(f"Failed to generate content for {file_desc.file_name}, skipping file")
                continue
            
            # Add the generated file content to the message history for context
            message_list.append({"role": "user", "content": f"Please confirm the content for {file_desc.file_name}"})
            message_list.append({"role": "assistant", "content": file_content})
            
            # Create directory structure in sandbox if needed
            dir_path = os.path.dirname(file_desc.file_name)
            if dir_path:
                try:
                    sandbox.commands.run(f"mkdir -p /home/user/{dir_path}")
                    logger.debug(f"Created directory: /home/user/{dir_path}")
                except Exception as e:
                    logger.error(f"Failed to create directory {dir_path}: {str(e)}")
                    continue
            
            # Write file to sandbox
            try:
                sandbox_path = f"/home/user/{file_desc.file_name}"
                sandbox.files.write(sandbox_path, file_content)
                logger.info(f"Wrote {file_desc.file_name} to sandbox")
            except Exception as e:
                logger.error(f"Failed to write {file_desc.file_name} to sandbox: {str(e)}")
        
        logger.info(f"Website generation completed in sandbox: {sandbox.sandbox_id}")
        return sandbox
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error generating website in sandbox: {str(e)}\n{error_details}")
        return None

def run_website_in_sandbox(sandbox, port=5000, public_access=False):
    """Run the generated website in the sandbox."""
    try:
        # Install requirements
        logger.info("Installing requirements...")
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Try to install requirements
                result = sandbox.commands.run("cd /home/user && pip install -r requirements.txt")
                logger.info("Requirements installed successfully")
                break  # If successful, exit the retry loop
            except Exception as e:
                error_message = str(e)
                logger.error(f"Error installing requirements (attempt {retry_count+1}/{max_retries}): {error_message}")
                retry_count += 1
                
                if retry_count >= max_retries:
                    logger.error(f"Failed to install requirements after {max_retries} attempts")
                    raise
                
                logger.info(f"Attempting to fix requirements.txt (attempt {retry_count}/{max_retries})")
                # Regenerate requirements.txt with error context
                file_desc = FileDescription(
                    file_name="requirements.txt",
                    description="Requirements file for the app"
                )
                fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                if fixed_content:
                    sandbox.files.write("/home/user/requirements.txt", fixed_content)
                    logger.info("Regenerated requirements.txt")
        
        # Start the server with similar retry logic
        if public_access:
            logger.info("Setting up gunicorn server...")
            retry_count = 0
            while retry_count < max_retries:
                try:
                    sandbox.commands.run("pip install gunicorn")
                    logger.info("Gunicorn installed successfully")
                    
                    # Create a log file in the sandbox for server output
                    sandbox.commands.run("touch /home/user/server.log")
                    
                    # Add more verbose logging for gunicorn
                    process = sandbox.commands.run(
                        "cd /home/user && gunicorn --bind 0.0.0.0:5000 --log-level debug app:app > server.log 2>&1", 
                        background=True
                    )
                    logger.info("Gunicorn server started")
                    
                    # Verify the server is actually running
                    sandbox.commands.run("sleep 2")  # Give it time to start
                    check_result = sandbox.commands.run("ps aux | grep gunicorn")
                    
                    # Check server logs for errors
                    server_logs = sandbox.commands.run("cat /home/user/server.log").stdout
                    logger.info(f"Initial server logs:\n{server_logs}")
                    
                    if "app:app" not in check_result.stdout:
                        logger.error("Gunicorn server failed to start properly")
                        raise Exception("Gunicorn server failed to start properly")
                    break
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Error starting gunicorn server (attempt {retry_count+1}/{max_retries}): {error_message}")
                    
                    # Get detailed error information
                    try:
                        error_logs = sandbox.commands.run("cat /home/user/server.log").stdout
                        logger.error(f"Server error logs:\n{error_logs}")
                    except:
                        logger.error("Could not retrieve server error logs")
                    
                    retry_count += 1
                    
                    if retry_count >= max_retries:
                        logger.error(f"Failed to start server after {max_retries} attempts")
                        raise
                    
                    logger.info(f"Attempting to fix app.py (attempt {retry_count}/{max_retries})")
                    # Regenerate app.py with error context
                    file_desc = FileDescription(
                        file_name="app.py",
                        description="Main application file"
                    )
                    fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                    if fixed_content:
                        sandbox.files.write("/home/user/app.py", fixed_content)
                        logger.info("Regenerated app.py")
        else:
            logger.info("Starting Flask development server...")
            retry_count = 0
            while retry_count < max_retries:
                try:
                    # Create a log file in the sandbox for Flask output
                    sandbox.commands.run("touch /home/user/flask.log")
                    
                    # Ensure Flask app runs with the right host and debug settings
                    process = sandbox.commands.run(
                        "cd /home/user && FLASK_ENV=development python -c 'from app import app; app.run(host=\"0.0.0.0\", port=5000, debug=True)' > flask.log 2>&1", 
                        background=True
                    )
                    logger.info("Flask development server started")
                    
                    # Check if server is running
                    sandbox.commands.run("sleep 2")  # Give it time to start
                    check_result = sandbox.commands.run("ps aux | grep 'python -c'")
                    
                    # Check server logs for errors
                    try:
                        flask_logs = sandbox.commands.run("cat /home/user/flask.log").stdout
                        logger.info(f"Initial Flask logs:\n{flask_logs}")
                    except:
                        logger.warning("Could not retrieve initial Flask logs")
                    
                    if "app.run" not in check_result.stdout:
                        logger.error("Flask server failed to start properly")
                        raise Exception("Flask server failed to start properly")
                    break
                except Exception as e:
                    error_message = str(e)
                    logger.error(f"Error starting Flask server (attempt {retry_count+1}/{max_retries}): {error_message}")
                    
                    # Get detailed error information
                    try:
                        error_logs = sandbox.commands.run("cat /home/user/flask.log").stdout
                        logger.error(f"Flask error logs:\n{error_logs}")
                    except:
                        logger.error("Could not retrieve Flask error logs")
                    
                    retry_count += 1
                    
                    if retry_count >= max_retries:
                        logger.error(f"Failed to start server after {max_retries} attempts")
                        raise
                    
                    logger.info(f"Attempting to fix app.py (attempt {retry_count}/{max_retries})")
                    # Regenerate app.py with error context
                    file_desc = FileDescription(
                        file_name="app.py",
                        description="Main application file"
                    )
                    fixed_content = regenerate_file_with_error(file_desc, error_message, sandbox)
                    if fixed_content:
                        sandbox.files.write("/home/user/app.py", fixed_content)
                        logger.info("Regenerated app.py")
        
        # Get public URL
        host = sandbox.get_host(port)
        url = f"https://{host}"
        logger.info(f"Website running at: {url}")
        
        # Add logging to help diagnose issues
        logger.info("Checking server logs...")
        try:
            logs = sandbox.commands.run("cd /home/user && cat *.log 2>/dev/null || echo 'No logs found'")
            logger.info(f"Server logs:\n{logs.stdout}")
        except Exception as log_error:
            logger.error(f"Could not retrieve logs: {log_error}")
        
        return {
            "process": process,
            "url": url,
            "sandbox": sandbox
        }
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error running website in sandbox: {str(e)}\n{error_details}")
        check_sandbox_logs(sandbox)  # Try to get as much log info as possible
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
            
        system_prompt = {
        "role": "system",
        "content": "You are a code generation assistant. ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary."
        }
        message_list = [system_prompt]
        
        user_prompt = f"""
        The file {file_description.file_name} needs to be fixed. When trying to use it, the following error occurred:
        
        ERROR: {error_message}
        
        Current file content:
        {current_content}
        
        Please fix the file and provide the corrected version. ALWAYS output ONLY valid, runnable code. DO NOT include explanations, markdown formatting, backticks, or extra text. No introductions, summaries, or additional commentary.
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

# Add a new function to check logs when errors occur
def check_sandbox_logs(sandbox):
    """Check the logs in the sandbox to diagnose errors."""
    try:
        logger.info("Checking sandbox logs for diagnostic information...")
        
        # Try to find and log any log files
        log_cmd = sandbox.commands.run("find /home/user -name '*.log' -type f -exec cat {} \\; 2>/dev/null || echo 'No log files found'")
        logger.info(f"Log files content:\n{log_cmd.stdout}")
        
        # Check running processes
        processes = sandbox.commands.run("ps aux")
        logger.info(f"Running processes:\n{processes.stdout}")
        
        # Check system errors
        stderr = sandbox.commands.run("dmesg | tail -n 50")
        logger.info(f"System logs:\n{stderr.stdout}")
        
        # Check Python traceback files if any
        traceback_files = sandbox.commands.run("find /home/user -name '*.err' -o -name '*.traceback' -type f -exec cat {} \\; 2>/dev/null || echo 'No error files found'")
        logger.info(f"Traceback files:\n{traceback_files.stdout}")
        
        # Try to get Flask app error information
        flask_errors = sandbox.commands.run("cd /home/user && python -c 'import traceback; print(traceback.format_exc())' 2>/dev/null || echo 'No Python traceback available'")
        logger.info(f"Flask error traceback:\n{flask_errors.stdout}")
        
        return True
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error checking logs: {str(e)}\n{error_details}")
        return False