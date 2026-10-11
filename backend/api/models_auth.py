"""
Authentication Models for GraphMind API
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class UserSignup(BaseModel):
    """User signup request model."""
    email: EmailStr = Field(..., description="User email address.", example="user@example.com")
    password: str = Field(..., min_length=6, description="Password with minimum 6 characters.", example="secret123")
    full_name: str = Field(..., min_length=1, description="User full name.", example="Tanmay Sharma")


class UserLogin(BaseModel):
    """User login request model."""
    email: EmailStr = Field(..., description="Registered user email.", example="user@example.com")
    password: str = Field(..., description="Registered user password.", example="secret123")


class Token(BaseModel):
    """JWT token response model."""
    access_token: str = Field(..., description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Token type.", example="bearer")
    user_id: str = Field(..., description="User UUID.", example="f4a2fca4-39d0-4028-8fb5-4f0b84b6c9d5")
    email: str = Field(..., description="User email.", example="user@example.com")
    full_name: str = Field(..., description="User full name.", example="Tanmay Sharma")


class UserResponse(BaseModel):
    """User information response model."""
    user_id: str = Field(..., description="User UUID.", example="f4a2fca4-39d0-4028-8fb5-4f0b84b6c9d5")
    email: str = Field(..., description="User email.", example="user@example.com")
    full_name: str = Field(..., description="User full name.", example="Tanmay Sharma")
    created_at: Optional[str] = Field(default=None, description="User creation timestamp in ISO-8601 format.")
