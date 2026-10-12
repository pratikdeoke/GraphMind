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

    # ------------------------------------------------------------------
    # End-to-End Encryption (E2EE) metadata
    # ------------------------------------------------------------------
    # NOTE: We only ever persist the random SALT and flags here. The user's PIN
    # and the derived AES key are NEVER written to the database.

    @staticmethod
    def get_encryption_profile(user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a user's encryption metadata (salt, enabled flag, hint).

        Args:
            user_id: User UUID.

        Returns:
            Dict with keys: encryption_salt, encryption_enabled,
            encryption_hint. Returns None if the user does not exist.
        """
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                SELECT encryption_salt, encryption_enabled, encryption_hint
                FROM users
                WHERE id = %s
            """, (user_id,))

            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def enable_encryption(user_id: str, salt: str, hint: Optional[str] = None) -> bool:
        """Persist the per-user salt and mark encryption as enabled.

        Args:
            user_id: User UUID.
            salt: Hex-encoded PBKDF2 salt.
            hint: Optional PIN hint chosen by the user.

        Returns:
            True if a row was updated.
        """
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET encryption_salt = %s,
                    encryption_enabled = TRUE,
                    encryption_hint = %s
                WHERE id = %s
            """, (salt, hint, user_id))

            return cur.rowcount > 0

    @staticmethod
    def update_encryption_salt(user_id: str, salt: str, hint: Optional[str] = None) -> bool:
        """Replace the per-user salt (used when the user changes their PIN).

        Args:
            user_id: User UUID.
            salt: New hex-encoded PBKDF2 salt.
            hint: Optional updated PIN hint.

        Returns:
            True if a row was updated.
        """
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET encryption_salt = %s,
                    encryption_hint = COALESCE(%s, encryption_hint)
                WHERE id = %s
            """, (salt, hint, user_id))

            return cur.rowcount > 0

    @staticmethod
    def disable_encryption(user_id: str) -> bool:
        """Disable encryption and remove the stored salt/hint.

        Only called AFTER all Neo4j nodes have been decrypted back to
        plaintext, so no data is ever lost.

        Args:
            user_id: User UUID.

        Returns:
            True if a row was updated.
        """
        with PostgresDB.get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET encryption_enabled = FALSE,
                    encryption_salt = NULL,
                    encryption_hint = NULL
                WHERE id = %s
            """, (user_id,))

            return cur.rowcount > 0
