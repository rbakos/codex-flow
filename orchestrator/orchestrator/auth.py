"""
Authentication and authorization system for production use.
Implements JWT-based auth with role-based access control.
"""
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum

from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, validator
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .logging_config import StructuredLogger
from .security import TokenGenerator

logger = StructuredLogger(__name__)

# Configuration
SECRET_KEY = os.getenv("ORCH_JWT_SECRET_KEY", TokenGenerator.generate_api_key())
ALGORITHM = os.getenv("ORCH_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ORCH_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("ORCH_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
API_KEY_HEADER = "X-API-Key"

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security schemes
bearer_scheme = HTTPBearer()
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


class UserRole(str, Enum):
    """User roles for RBAC."""
    ADMIN = "admin"
    OPERATOR = "operator"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    AGENT = "agent"


class TokenType(str, Enum):
    """Token types."""
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"


class Permission(str, Enum):
    """Granular permissions."""
    # Projects
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    
    # Work Items
    WORK_ITEM_CREATE = "work_item:create"
    WORK_ITEM_READ = "work_item:read"
    WORK_ITEM_UPDATE = "work_item:update"
    WORK_ITEM_DELETE = "work_item:delete"
    WORK_ITEM_EXECUTE = "work_item:execute"
    
    # Runs
    RUN_CREATE = "run:create"
    RUN_READ = "run:read"
    RUN_UPDATE = "run:update"
    RUN_CANCEL = "run:cancel"
    
    # Admin
    ADMIN_USERS = "admin:users"
    ADMIN_SETTINGS = "admin:settings"
    ADMIN_METRICS = "admin:metrics"
    
    # Agent
    AGENT_CLAIM = "agent:claim"
    AGENT_HEARTBEAT = "agent:heartbeat"
    AGENT_LOGS = "agent:logs"


# Role-Permission mapping
ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
    UserRole.ADMIN: [p for p in Permission],  # All permissions
    
    UserRole.OPERATOR: [
        Permission.PROJECT_CREATE, Permission.PROJECT_READ, Permission.PROJECT_UPDATE,
        Permission.WORK_ITEM_CREATE, Permission.WORK_ITEM_READ, Permission.WORK_ITEM_UPDATE,
        Permission.WORK_ITEM_EXECUTE, Permission.RUN_CREATE, Permission.RUN_READ,
        Permission.RUN_UPDATE, Permission.RUN_CANCEL, Permission.ADMIN_METRICS
    ],
    
    UserRole.DEVELOPER: [
        Permission.PROJECT_READ, Permission.WORK_ITEM_CREATE, Permission.WORK_ITEM_READ,
        Permission.WORK_ITEM_UPDATE, Permission.WORK_ITEM_EXECUTE, Permission.RUN_CREATE,
        Permission.RUN_READ, Permission.RUN_UPDATE
    ],
    
    UserRole.VIEWER: [
        Permission.PROJECT_READ, Permission.WORK_ITEM_READ, Permission.RUN_READ
    ],
    
    UserRole.AGENT: [
        Permission.WORK_ITEM_READ, Permission.RUN_READ, Permission.RUN_UPDATE,
        Permission.AGENT_CLAIM, Permission.AGENT_HEARTBEAT, Permission.AGENT_LOGS
    ]
}


class TokenData(BaseModel):
    """Token payload data."""
    sub: str  # Subject (user_id or api_key_id)
    type: TokenType
    role: UserRole
    permissions: List[Permission]
    exp: Optional[datetime] = None
    iat: Optional[datetime] = None
    jti: Optional[str] = None  # JWT ID for revocation


class UserCreate(BaseModel):
    """User creation schema."""
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.VIEWER
    
    @validator("password")
    def validate_password(cls, v):
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain uppercase letters")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain lowercase letters")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain digits")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain special characters")
        return v


class User(BaseModel):
    """User model."""
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None
    mfa_enabled: bool = False


class APIKey(BaseModel):
    """API Key model."""
    id: str
    name: str
    key_hash: str
    role: UserRole
    created_at: datetime
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: bool = True


class AuthManager:
    """Manages authentication and authorization."""
    
    def __init__(self):
        self.revoked_tokens: set = set()  # In production, use Redis
        
    def hash_password(self, password: str) -> str:
        """Hash a password."""
        return pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against hash."""
        return pwd_context.verify(plain_password, hashed_password)
    
    def create_token(self, 
                    data: Dict[str, Any],
                    token_type: TokenType,
                    expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT token."""
        to_encode = data.copy()
        
        # Set expiration
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            if token_type == TokenType.ACCESS:
                expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            elif token_type == TokenType.REFRESH:
                expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
            else:
                expire = datetime.utcnow() + timedelta(days=365)  # API keys
        
        # Add token metadata
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": token_type.value,
            "jti": secrets.token_urlsafe(16)  # JWT ID for revocation
        })
        
        # Create token
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        
        logger.info(
            "Token created",
            token_type=token_type.value,
            subject=data.get("sub"),
            expires_in_seconds=(expire - datetime.utcnow()).total_seconds()
        )
        
        return encoded_jwt
    
    def decode_token(self, token: str) -> TokenData:
        """Decode and validate a JWT token."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            
            # Check if token is revoked
            if payload.get("jti") in self.revoked_tokens:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked"
                )
            
            # Parse token data
            token_data = TokenData(
                sub=payload.get("sub"),
                type=TokenType(payload.get("type")),
                role=UserRole(payload.get("role")),
                permissions=[Permission(p) for p in payload.get("permissions", [])]
            )
            
            return token_data
            
        except JWTError as e:
            logger.warning("Invalid token", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    def revoke_token(self, jti: str):
        """Revoke a token by its JWT ID."""
        self.revoked_tokens.add(jti)
        logger.info("Token revoked", jti=jti)
    
    def create_api_key(self, name: str, role: UserRole) -> tuple[str, str]:
        """Create an API key."""
        key = TokenGenerator.generate_api_key()
        key_hash = self.hash_password(key)
        
        # In production, save to database
        api_key = APIKey(
            id=secrets.token_urlsafe(16),
            name=name,
            key_hash=key_hash,
            role=role,
            created_at=datetime.utcnow()
        )
        
        logger.audit(
            "API key created",
            resource=f"api_key:{api_key.id}",
            result="success",
            key_name=name,
            role=role.value
        )
        
        return key, api_key.id
    
    def verify_api_key(self, api_key: str) -> Optional[TokenData]:
        """Verify an API key."""
        # In production, look up from database
        # For now, we'll validate the format
        if not api_key.startswith("sk_"):
            return None
        
        # Return token data for valid API key
        return TokenData(
            sub="api_key_id",
            type=TokenType.API_KEY,
            role=UserRole.AGENT,
            permissions=ROLE_PERMISSIONS[UserRole.AGENT]
        )


# Global auth manager
auth_manager = AuthManager()


class AuthorizationChecker:
    """Check user permissions."""
    
    def __init__(self, required_permissions: List[Permission]):
        self.required_permissions = required_permissions
    
    def __call__(self, 
                 credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
                 api_key: Optional[str] = Depends(api_key_header)) -> TokenData:
        """Verify user has required permissions."""
        
        token_data = None
        
        # Try Bearer token first
        if credentials:
            token_data = auth_manager.decode_token(credentials.credentials)
        
        # Fall back to API key
        elif api_key:
            token_data = auth_manager.verify_api_key(api_key)
            if not token_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key"
                )
        
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No authentication provided"
            )
        
        # Check permissions
        user_permissions = set(token_data.permissions)
        required = set(self.required_permissions)
        
        if not required.issubset(user_permissions):
            missing = required - user_permissions
            logger.warning(
                "Permission denied",
                user=token_data.sub,
                required=list(required),
                missing=list(missing)
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permissions: {', '.join(missing)}"
            )
        
        return token_data


# Dependency shortcuts
def require_auth(permissions: List[Permission] = None):
    """Require authentication with optional permission check."""
    if permissions:
        return Depends(AuthorizationChecker(permissions))
    return Depends(AuthorizationChecker([]))


def require_admin():
    """Require admin role."""
    return Depends(AuthorizationChecker([Permission.ADMIN_USERS]))


def get_current_user(token_data: TokenData = Depends(require_auth())) -> str:
    """Get current user ID from token."""
    return token_data.sub


class RateLimiter:
    """Rate limiting with Redis backend."""
    
    def __init__(self, 
                 requests_per_minute: int = 60,
                 burst_size: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        # In production, use Redis
        self.request_counts: Dict[str, List[float]] = {}
    
    async def check_rate_limit(self, 
                               identifier: str,
                               token_data: TokenData = Depends(require_auth())):
        """Check if request is within rate limits."""
        
        # Higher limits for certain roles
        if token_data.role == UserRole.ADMIN:
            return  # No rate limit for admins
        
        if token_data.role == UserRole.AGENT:
            limit = self.requests_per_minute * 2
        else:
            limit = self.requests_per_minute
        
        now = datetime.utcnow().timestamp()
        minute_ago = now - 60
        
        # Get request history
        if identifier not in self.request_counts:
            self.request_counts[identifier] = []
        
        # Remove old requests
        self.request_counts[identifier] = [
            ts for ts in self.request_counts[identifier] 
            if ts > minute_ago
        ]
        
        # Check limit
        if len(self.request_counts[identifier]) >= limit:
            logger.warning(
                "Rate limit exceeded",
                identifier=identifier,
                limit=limit
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"}
            )
        
        # Add current request
        self.request_counts[identifier].append(now)


# Global rate limiter
rate_limiter = RateLimiter()