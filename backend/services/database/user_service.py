"""
User Service - PostgreSQL-based user management
"""

from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import bcrypt
from database.postgres import PostgresDB


class UserService:
    """Manage users in PostgreSQL."""
    
    @staticmethod
    def create_user(email: str, password: str, full_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new user.
        
        Args:
            email: User email
            password: Plain text password
            full_name: Optional full name
            
        Returns:
            Created user dict
        """
        # Hash password with bcrypt
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        neo4j_user_id = f"user_{uuid.uuid4().hex[:16]}"
        
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                INSERT INTO users (email, hashed_password, full_name, neo4j_user_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id, email, full_name, neo4j_user_id, created_at, is_active
            """, (email, hashed_password, full_name, neo4j_user_id))
            
            user = cur.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT id, email, hashed_password, full_name, neo4j_user_id, 
                       is_active, is_verified, created_at, last_login
                FROM users
                WHERE email = %s
            """, (email,))
            
            user = cur.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by UUID."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT id, email, full_name, neo4j_user_id, 
                       is_active, is_verified, created_at, last_login
                FROM users
                WHERE id = %s
            """, (user_id,))
            
            user = cur.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def get_user_by_neo4j_id(neo4j_user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by Neo4j ID."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT id, email, full_name, neo4j_user_id, 
                       is_active, is_verified, created_at, last_login
                FROM users
                WHERE neo4j_user_id = %s
            """, (neo4j_user_id,))
            
            user = cur.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify password."""
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    @staticmethod
    def update_last_login(user_id: str):
        """Update user's last login timestamp."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET last_login = NOW()
                WHERE id = %s
            """, (user_id,))
    
    @staticmethod
    def get_all_users(limit: int = 100, offset: int = 0) -> list:
        """Get all users with pagination."""
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT id, email, full_name, neo4j_user_id, 
                       is_active, created_at, last_login
                FROM users
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            
            return [dict(row) for row in cur.fetchall()]
