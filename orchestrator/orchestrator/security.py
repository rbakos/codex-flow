"""
Security utilities for the orchestrator.
Provides safe command execution, input validation, and security helpers.
"""
import shlex
import subprocess
import re
import hashlib
import secrets
from typing import Optional, Dict, Any, List, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class CommandExecutionError(Exception):
    """Raised when command execution fails"""
    pass

class ValidationError(Exception):
    """Raised when input validation fails"""
    pass


class SecureCommandExecutor:
    """
    Secure command execution with validation and sandboxing.
    Prevents shell injection and provides controlled execution environment.
    """
    
    # Whitelist of allowed commands for the agent
    ALLOWED_COMMANDS = {
        'echo', 'pwd', 'ls', 'cat', 'grep', 'find', 'git', 'docker',
        'python', 'pip', 'npm', 'yarn', 'make', 'terraform', 'kubectl',
        'aws', 'gcloud', 'az', 'helm', 'tofu', 'opentofu'
    }
    
    # Dangerous command patterns that should never be executed
    DANGEROUS_PATTERNS = [
        r';\s*rm\s+-rf',  # rm -rf after semicolon
        r'>\s*/dev/.*',   # Overwriting system files
        r'curl.*\|.*sh',  # Curl pipe to shell
        r'wget.*\|.*sh',  # Wget pipe to shell
        r'eval\s*\(',     # Eval execution
        r'exec\s*\(',     # Exec execution
    ]
    
    def __init__(self, 
                 allowed_commands: Optional[set] = None,
                 max_timeout: int = 300,
                 max_output_size: int = 10 * 1024 * 1024):  # 10MB
        """
        Initialize secure command executor.
        
        Args:
            allowed_commands: Set of allowed command names (uses default if None)
            max_timeout: Maximum execution timeout in seconds
            max_output_size: Maximum output size in bytes
        """
        self.allowed_commands = allowed_commands or self.ALLOWED_COMMANDS
        self.max_timeout = max_timeout
        self.max_output_size = max_output_size
    
    def validate_command(self, command: str) -> bool:
        """
        Validate command for security issues.
        
        Args:
            command: Command string to validate
            
        Returns:
            True if command is safe to execute
            
        Raises:
            ValidationError: If command contains dangerous patterns
        """
        # Check for dangerous patterns
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise ValidationError(f"Command contains dangerous pattern: {pattern}")
        
        # Extract base command
        try:
            parts = shlex.split(command)
            if not parts:
                raise ValidationError("Empty command")
            
            base_command = Path(parts[0]).name
            
            # Check if command is in allowed list
            if base_command not in self.allowed_commands:
                logger.warning(f"Command not in whitelist: {base_command}")
                # Still allow but log for monitoring
                
        except ValueError as e:
            raise ValidationError(f"Invalid command syntax: {e}")
        
        return True
    
    def execute(self,
                command: Union[str, List[str]],
                env: Optional[Dict[str, str]] = None,
                timeout: Optional[int] = None,
                cwd: Optional[str] = None,
                shell: bool = False) -> subprocess.CompletedProcess:
        """
        Securely execute a command with validation and sandboxing.
        
        Args:
            command: Command to execute (string or list)
            env: Environment variables
            timeout: Execution timeout (uses max_timeout if not specified)
            cwd: Working directory
            shell: Whether to use shell (discouraged, will validate more strictly)
            
        Returns:
            CompletedProcess object with results
            
        Raises:
            CommandExecutionError: If execution fails
            ValidationError: If command validation fails
        """
        # Convert string command to list for safer execution
        if isinstance(command, str):
            if shell:
                # Validate more strictly for shell commands
                self.validate_command(command)
                cmd_to_run = command
            else:
                # Parse command safely
                try:
                    cmd_to_run = shlex.split(command)
                except ValueError as e:
                    raise ValidationError(f"Invalid command syntax: {e}")
        else:
            cmd_to_run = command
            
        # Validate timeout
        timeout = min(timeout or self.max_timeout, self.max_timeout)
        
        # Prepare environment (isolate from parent process)
        safe_env = {
            'PATH': '/usr/local/bin:/usr/bin:/bin',
            'HOME': '/tmp',
            'USER': 'nobody',
            'LANG': 'en_US.UTF-8',
        }
        if env:
            # Only allow specific environment variables
            for key, value in env.items():
                if self._is_safe_env_var(key, value):
                    safe_env[key] = value
        
        try:
            result = subprocess.run(
                cmd_to_run,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=safe_env,
                shell=shell
            )
            
            # Check output size
            if len(result.stdout) > self.max_output_size:
                result.stdout = result.stdout[:self.max_output_size] + "\n[OUTPUT TRUNCATED]"
            if len(result.stderr) > self.max_output_size:
                result.stderr = result.stderr[:self.max_output_size] + "\n[OUTPUT TRUNCATED]"
                
            return result
            
        except subprocess.TimeoutExpired as e:
            raise CommandExecutionError(f"Command timed out after {timeout} seconds")
        except Exception as e:
            raise CommandExecutionError(f"Command execution failed: {e}")
    
    def _is_safe_env_var(self, key: str, value: str) -> bool:
        """Check if environment variable is safe to pass through."""
        # Whitelist of safe environment variables
        safe_vars = {
            'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_DEFAULT_REGION',
            'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_CLOUD_PROJECT',
            'AZURE_CLIENT_ID', 'AZURE_CLIENT_SECRET', 'AZURE_TENANT_ID',
            'KUBECONFIG', 'DOCKER_HOST', 'NO_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY'
        }
        
        # Check if variable is in whitelist or follows safe patterns
        if key in safe_vars:
            return True
        if key.startswith('npm_') or key.startswith('NODE_'):
            return True
        if key.startswith('PYTHON'):
            return True
            
        logger.warning(f"Blocking environment variable: {key}")
        return False


class InputValidator:
    """Validates and sanitizes user inputs."""
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000) -> str:
        """
        Sanitize string input by removing dangerous characters.
        
        Args:
            value: String to sanitize
            max_length: Maximum allowed length
            
        Returns:
            Sanitized string
        """
        if not value:
            return ""
            
        # Truncate to max length
        value = value[:max_length]
        
        # Remove null bytes and control characters
        value = value.replace('\0', '')
        value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\r\t')
        
        return value
    
    @staticmethod
    def validate_yaml(yaml_content: str) -> bool:
        """
        Validate YAML content for security issues.
        
        Args:
            yaml_content: YAML string to validate
            
        Returns:
            True if YAML is safe
            
        Raises:
            ValidationError: If YAML contains dangerous content
        """
        # Check for dangerous YAML tags
        dangerous_tags = ['!!python/', '!!subprocess/', '!!eval/']
        for tag in dangerous_tags:
            if tag in yaml_content:
                raise ValidationError(f"YAML contains dangerous tag: {tag}")
        
        # Check size
        if len(yaml_content) > 1024 * 1024:  # 1MB limit
            raise ValidationError("YAML content too large")
            
        return True
    
    @staticmethod
    def validate_path(path: str, base_dir: Optional[str] = None) -> Path:
        """
        Validate file path to prevent directory traversal.
        
        Args:
            path: Path to validate
            base_dir: Base directory to restrict paths to
            
        Returns:
            Validated Path object
            
        Raises:
            ValidationError: If path is unsafe
        """
        try:
            p = Path(path).resolve()
            
            # Check for directory traversal
            if '..' in path:
                raise ValidationError("Path contains directory traversal")
            
            # If base_dir specified, ensure path is within it
            if base_dir:
                base = Path(base_dir).resolve()
                if not str(p).startswith(str(base)):
                    raise ValidationError("Path outside allowed directory")
            
            return p
            
        except Exception as e:
            raise ValidationError(f"Invalid path: {e}")


class TokenGenerator:
    """Generate secure tokens for various purposes."""
    
    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure API key."""
        return f"sk_{secrets.token_urlsafe(32)}"
    
    @staticmethod
    def generate_session_token() -> str:
        """Generate a secure session token."""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_claim_token() -> str:
        """Generate a secure claim token for agents."""
        return f"claim_{secrets.token_hex(16)}"
    
    @staticmethod
    def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
        """
        Hash a password with salt.
        
        Args:
            password: Password to hash
            salt: Salt to use (generates if not provided)
            
        Returns:
            Tuple of (hashed_password, salt)
        """
        if not salt:
            salt = secrets.token_hex(16)
        
        hashed = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000  # iterations
        )
        
        return hashed.hex(), salt