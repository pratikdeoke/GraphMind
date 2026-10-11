"""
Authentication Service - User management and JWT tokens with PostgreSQL
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict
from jose import JWTError, jwt
from dotenv import load_dotenv
from services.database.user_service import UserService

load_dotenv()


class AuthService:
    """Handle user authentication and JWT token management."""
    
    def __init__(self):
        """Initialize auth service."""
        self.secret_key = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 60 * 24 * 7  # 7 days
        self.user_service = UserService()
    
    def create_user(self, email: str, password: str, full_name: str) -> Optional[Dict]:
        """
        Create a new user in PostgreSQL.
        
        Returns:
            User dict if successful, None if email already exists
        """
        try:
            user = self.user_service.create_user(email, password, full_name)
            if user:
                return {
                    "user_id": str(user["id"]),
                    "neo4j_user_id": user["neo4j_user_id"],
                    "email": user["email"],
                    "full_name": user["full_name"],
                    "created_at": user["created_at"].isoformat() if user["created_at"] else None
                }
            return None
        except Exception as e:
            print(f"Error creating user: {e}")
            return None
    
    def authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        """
        Authenticate user with email and password.
        
        Returns:
            User dict if successful, None if authentication fails
        """
        user = self.user_service.get_user_by_email(email)
        if not user:
            return None
        
        if not self.user_service.verify_password(password, user["hashed_password"]):
            return None
        
        # Update last login
        self.user_service.update_last_login(str(user["id"]))
        
        return {
            "user_id": str(user["id"]),
            "neo4j_user_id": user["neo4j_user_id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by PostgreSQL UUID."""
        user = self.user_service.get_user_by_id(user_id)
        if user:
            return {
                "user_id": str(user["id"]),
                "neo4j_user_id": user["neo4j_user_id"],
                "email": user["email"],
                "full_name": user["full_name"]
            }
        return None
    
    def create_access_token(self, user_id: str, email: str) -> str:
        """
        Create JWT access token.
        
        Args:
            user_id: User's PostgreSQL UUID
            email: User's email
            
        Returns:
            JWT token string
        """
        expires_delta = timedelta(minutes=self.access_token_expire_minutes)
        expire = datetime.utcnow() + expires_delta
        
        to_encode = {
            "sub": user_id,
            "email": email,
            "exp": expire
        }
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Verify JWT token and extract payload.
        
        Args:
            token: JWT token string
            
        Returns:
            Payload dict if valid, None if invalid
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            user_id: str = payload.get("sub")
            email: str = payload.get("email")
            
            if user_id is None or email is None:
                return None
            
            return {"user_id": user_id, "email": email}
        except JWTError:
            return None


# Global auth service instance
auth_service = AuthService()
