"""
Authentication Routes - Login, Signup, Token verification
"""

from fastapi import APIRouter, HTTPException, status, Header
from typing import Optional
from api.models_auth import UserSignup, UserLogin, Token, UserResponse
from services.auth.auth_service import auth_service

router = APIRouter()


@router.post(
    "/signup",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create user account",
    description="Register a new user and return a bearer JWT token.",
    responses={
        201: {"description": "User created and token issued."},
        400: {"description": "Email already registered."}
    }
)
async def signup(user_data: UserSignup):
    """
    Register a new user.
    
    Args:
        user_data: User signup information (email, password, full_name)
        
    Returns:
        JWT token and user information
        
    Raises:
        HTTPException: If email already exists
    """
    # Create user
    user = auth_service.create_user(
        email=user_data.email,
        password=user_data.password,
        full_name=user_data.full_name
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create access token
    access_token = auth_service.create_access_token(
        user_id=user["user_id"],
        email=user["email"]
    )
    
    return Token(
        access_token=access_token,
        user_id=user["user_id"],
        email=user["email"],
        full_name=user["full_name"]
    )


@router.post(
    "/login",
    response_model=Token,
    summary="Login user",
    description="Authenticate with email/password and return a bearer JWT token.",
    responses={
        200: {"description": "Authentication successful."},
        401: {"description": "Invalid credentials."}
    }
)
async def login(credentials: UserLogin):
    """
    Authenticate user and return JWT token.
    
    Args:
        credentials: User login credentials (email, password)
        
    Returns:
        JWT token and user information
        
    Raises:
        HTTPException: If authentication fails
    """
    # Authenticate user
    user = auth_service.authenticate_user(
        email=credentials.email,
        password=credentials.password
    )
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Create access token
    access_token = auth_service.create_access_token(
        user_id=user["user_id"],
        email=user["email"]
    )
    
    return Token(
        access_token=access_token,
        user_id=user["user_id"],
        email=user["email"],
        full_name=user["full_name"]
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Return profile information for the currently authenticated user.",
    responses={
        200: {"description": "Current user profile."},
        401: {"description": "Missing, invalid, or expired token."},
        404: {"description": "User not found."}
    }
)
async def get_current_user(
    authorization: Optional[str] = Header(
        default=None,
        description="Bearer token. Format: 'Bearer <access_token>'"
    )
):
    """
    Get current user information from JWT token.
    
    Args:
        authorization: Authorization header with Bearer token
        
    Returns:
        Current user information
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Extract token from "Bearer <token>"
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Verify token
    payload = auth_service.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Get user from PostgreSQL
    user = auth_service.get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse(
        user_id=user["user_id"],
        email=user["email"],
        full_name=user["full_name"],
        created_at=user.get("created_at")
    )
