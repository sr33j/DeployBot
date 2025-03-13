#!/usr/bin/env python3

import os
import time
import boto3
import paramiko
import dotenv
from pathlib import Path
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv.load_dotenv()

# AWS credentials from environment variables
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')  # Default to us-east-1 if not specified

# EC2 configuration
INSTANCE_TYPE = 't2.micro'  # Free tier eligible instance type

# Whitelist IPs that can access the application
ALLOWED_IPS = ['54.157.14.34/32', '47.230.210.140/32']

KEY_NAME = 'deploybot-key'  # SSH key pair name (will be created if it doesn't exist)
SECURITY_GROUP_NAME = 'deploybot-sg'  # Security group name (will be created if it doesn't exist)
INSTANCE_NAME = 'deploybot-server'  # Name tag for the EC2 instance

# Application configuration
APP_DIR = '/home/ubuntu/deploybot'
SERVICE_NAME = 'deploybot'

def get_or_create_security_group(ec2_client):
    """Get or create a security group for the application."""
    try:
        response = ec2_client.describe_security_groups(
            GroupNames=[SECURITY_GROUP_NAME]
        )
        security_group_id = response['SecurityGroups'][0]['GroupId']
        
        # Update the existing security group with new rules
        print(f"Updating security group rules for: {SECURITY_GROUP_NAME}")
        
        # First revoke all existing inbound rules
        ec2_client.revoke_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=response['SecurityGroups'][0].get('IpPermissions', [])
        )
        
        # Add new rules
        ip_permissions = [
            # SSH from anywhere for administration
            {
                'IpProtocol': 'tcp',
                'FromPort': 22,
                'ToPort': 22,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
        
        # Add restricted access for HTTP, HTTPS and application port
        for port in [80, 443, 8000]:
            permission = {
                'IpProtocol': 'tcp',
                'FromPort': port,
                'ToPort': port,
                'IpRanges': [{'CidrIp': ip} for ip in ALLOWED_IPS]
            }
            ip_permissions.append(permission)
            
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=ip_permissions
        )
        
        return security_group_id
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            print(f"Creating security group: {SECURITY_GROUP_NAME}")
            # Create a new security group
            response = ec2_client.create_security_group(
                GroupName=SECURITY_GROUP_NAME,
                Description='Security group for DeployBot FastAPI application'
            )
            security_group_id = response['GroupId']
            
            # Add inbound rules
            ip_permissions = [
                # SSH from anywhere for administration
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }
            ]
            
            # Add restricted access for HTTP, HTTPS and application port
            for port in [80, 443, 8000]:
                permission = {
                    'IpProtocol': 'tcp',
                    'FromPort': port,
                    'ToPort': port,
                    'IpRanges': [{'CidrIp': ip} for ip in ALLOWED_IPS]
                }
                ip_permissions.append(permission)
                
            ec2_client.authorize_security_group_ingress(
                GroupId=security_group_id,
                IpPermissions=ip_permissions
            )
            
            return security_group_id
        else:
            raise

def get_or_create_key_pair(ec2_client):
    """Get or create an SSH key pair for connecting to the EC2 instance."""
    key_file = Path(f"{KEY_NAME}.pem")
    
    try:
        # Check if key pair exists in AWS
        ec2_client.describe_key_pairs(KeyNames=[KEY_NAME])
        print(f"Key pair {KEY_NAME} already exists.")
        
        # Check if key file exists locally
        if not key_file.exists():
            print(f"Warning: Key file {key_file} not found locally. You may not be able to connect to the instance.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidKeyPair.NotFound':
            # Create a new key pair
            print(f"Creating new key pair: {KEY_NAME}")
            response = ec2_client.create_key_pair(KeyName=KEY_NAME)
            
            # Save private key to a file
            with open(key_file, 'w') as f:
                f.write(response['KeyMaterial'])
            
            # Set proper permissions for the key file
            os.chmod(key_file, 0o400)
            print(f"Key pair created and saved to {key_file}")
        else:
            raise
    
    return KEY_NAME, key_file

def get_or_launch_instance(ec2_resource, security_group_id):
    """Get an existing instance or launch a new one."""
    # Check for existing instances with the tag
    instances = list(ec2_resource.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [INSTANCE_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running', 'pending']}
        ]
    ))
    
    if instances:
        instance = instances[0]
        print(f"Found existing instance: {instance.id}")
        return instance
    
    # Launch a new instance
    print(f"Launching new EC2 instance: {INSTANCE_NAME}")
    instances = ec2_resource.create_instances(
        ImageId='ami-0261755bbcb8c4a84',  # Ubuntu 20.04 LTS in us-east-1
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[security_group_id],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': INSTANCE_NAME}]
            }
        ]
    )
    
    instance = instances[0]
    print(f"Waiting for instance {instance.id} to start...")
    instance.wait_until_running()
    instance.reload()  # Refresh instance data
    
    return instance

def wait_for_ssh(hostname, retries=10, delay=15):
    """Wait for SSH to become available on the instance."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    for i in range(retries):
        try:
            print(f"Trying to connect via SSH (attempt {i+1}/{retries})...")
            ssh.connect(
                hostname=hostname,
                username='ubuntu',
                key_filename=f"{KEY_NAME}.pem",
                timeout=10
            )
            print("SSH connection successful!")
            ssh.close()
            return True
        except Exception as e:
            print(f"SSH connection failed: {e}")
            if i < retries - 1:
                print(f"Waiting {delay} seconds before next attempt...")
                time.sleep(delay)
    
    print("Failed to establish SSH connection after multiple attempts.")
    return False

def setup_instance(hostname):
    """Set up the EC2 instance with required packages and configurations."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=hostname,
        username='ubuntu',
        key_filename=f"{KEY_NAME}.pem"
    )
    
    # Update package lists and install dependencies
    commands = [
        "sudo apt-get update",
        "sudo apt-get install -y python3-pip python3-venv nginx",
        f"mkdir -p {APP_DIR}",
        # Setup systemd service
        f"""sudo bash -c 'cat > /etc/systemd/system/{SERVICE_NAME}.service << EOF
[Unit]
Description=DeployBot FastAPI Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory={APP_DIR}
ExecStart={APP_DIR}/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
Environment="PATH={APP_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
EOF'""",
        # Configure Nginx as a reverse proxy
        """sudo bash -c 'cat > /etc/nginx/sites-available/deploybot << EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
}
EOF'""",
        "sudo ln -sf /etc/nginx/sites-available/deploybot /etc/nginx/sites-enabled/",
        "sudo rm -f /etc/nginx/sites-enabled/default",
        "sudo nginx -t",
        "sudo systemctl restart nginx",
        "sudo systemctl daemon-reload",
        "sudo systemctl enable " + SERVICE_NAME
    ]
    
    for cmd in commands:
        print(f"Running: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            print(f"Error executing command: {stderr.read().decode()}")
    
    ssh.close()
    print("Instance setup completed successfully.")

def deploy_application(hostname):
    """Deploy the application code to the EC2 instance."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=hostname,
        username='ubuntu',
        key_filename=f"{KEY_NAME}.pem"
    )
    
    # Create virtual environment if it doesn't exist
    stdin, stdout, stderr = ssh.exec_command(f"test -d {APP_DIR}/venv || python3 -m venv {APP_DIR}/venv")
    exit_status = stdout.channel.recv_exit_status()
    
    # Upload application files using SFTP
    sftp = ssh.open_sftp()
    
    # Get list of local files to upload (excluding .git, __pycache__, etc.)
    local_files = []
    for root, dirs, files in os.walk('.'):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'temp', 'venv']]
        
        for file in files:
            if file.endswith(('.py', '.txt')) or file == '.env':
                if file == 'deploy_to_ec2.py':
                    continue

                local_path = os.path.join(root, file)
                # Convert to relative path
                rel_path = os.path.relpath(local_path, '.')
                local_files.append(rel_path)
    
    # Upload each file
    for file_path in local_files:
        remote_path = f"{APP_DIR}/{file_path}"
        remote_dir = os.path.dirname(remote_path)
        
        # Create remote directory if it doesn't exist
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_dir}")
            stdout.channel.recv_exit_status()
        
        print(f"Uploading {file_path} to {remote_path}")
        sftp.put(file_path, remote_path)
    
    sftp.close()
    
    # Install dependencies and restart service
    commands = [
        # Upgrade pip first
        f"{APP_DIR}/venv/bin/pip install --upgrade pip",
        
        # Install specific required packages first (uvicorn, fastapi, etc.)
        f"{APP_DIR}/venv/bin/pip install uvicorn fastapi",
        
        # Install from requirements.txt
        f"{APP_DIR}/venv/bin/pip install -r {APP_DIR}/requirements.txt",
        
        # Additional fallback for packages that might have specific constraints
        f"cd {APP_DIR} && source venv/bin/activate && grep -v '@' requirements.txt | cut -d= -f1 | xargs pip install",
        
        # Reset any failed service attempts
        "sudo systemctl reset-failed " + SERVICE_NAME,
        
        # Restart the service
        "sudo systemctl restart " + SERVICE_NAME,
        
        # Wait a moment to ensure the service starts
        "sleep 3",
        
        # Check service status
        "sudo systemctl status " + SERVICE_NAME
    ]
    
    for cmd in commands:
        print(f"Running: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error_output = stderr.read().decode()
            print(f"Error executing command: {error_output}")
            # Continue with other commands rather than stopping deployment on first error
            print("Continuing with deployment despite error...")
        else:
            success_output = stdout.read().decode()
            print(f"Command output: {success_output[:500]}..." if len(success_output) > 500 else f"Command output: {success_output}")
    
    ssh.close()
    print("Application deployed successfully!")

def main():
    # Validate AWS credentials
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise ValueError("AWS credentials not found. Make sure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set in .env file.")
    
    # Initialize AWS clients
    try:
        ec2_client = boto3.client(
            'ec2',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        
        ec2_resource = boto3.resource(
            'ec2',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
    except Exception as e:
        print(f"Error connecting to AWS: {e}")
        return
    
    try:
        # Get or create security group
        security_group_id = get_or_create_security_group(ec2_client)
        print(f"Using security group: {security_group_id}")
        
        # Get or create key pair
        key_name, key_file = get_or_create_key_pair(ec2_client)
        
        # Get or launch EC2 instance
        instance = get_or_launch_instance(ec2_resource, security_group_id)
        print(f"Instance {instance.id} is {instance.state['Name']}")
        print(f"Public DNS: {instance.public_dns_name}")
        print(f"Public IP: {instance.public_ip_address}")
        
        # Wait for SSH to become available
        if wait_for_ssh(instance.public_dns_name):
            # Set up the instance
            setup_instance(instance.public_dns_name)
            
            # Deploy the application
            deploy_application(instance.public_dns_name)
            
            print("\nDeployment completed successfully!")
            print(f"Your application is now running at: http://{instance.public_ip_address}")
            print(f"You can SSH into the instance using: ssh -i {KEY_NAME}.pem ubuntu@{instance.public_dns_name}")
        else:
            print("Could not establish SSH connection. Deployment failed.")
    
    except Exception as e:
        print(f"Error during deployment: {e}")

if __name__ == "__main__":
    main()
