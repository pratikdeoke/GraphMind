"""
PostgreSQL Database Connection and Pool Management
"""

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Optional
from config.settings import Settings


class PostgresDB:
    """PostgreSQL connection pool manager."""
    
    _pool: Optional[pool.ThreadedConnectionPool] = None
    
    @classmethod
    def initialize(cls):
        """Initialize connection pool."""
        if cls._pool is None:
            try:
                cls._pool = pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    host=Settings.POSTGRES_HOST,
                    port=Settings.POSTGRES_PORT,
                    database=Settings.POSTGRES_DB,
                    user=Settings.POSTGRES_USER,
                    password=Settings.POSTGRES_PASSWORD
                )
                print(f"[OK] PostgreSQL connection pool initialized")
            except Exception as e:
                print(f"[ERROR] Failed to initialize PostgreSQL pool: {e}")
                raise
    
    @classmethod
    @contextmanager
    def get_connection(cls):
        """
        Get a connection from the pool.
        
        Usage:
            with PostgresDB.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM users")
        """
        if cls._pool is None:
            cls.initialize()
        
        conn = cls._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cls._pool.putconn(conn)
    
    @classmethod
    @contextmanager
    def get_cursor(cls, cursor_factory=RealDictCursor):
        """
        Get a dict cursor from the pool.
        
        Usage:
            with PostgresDB.get_cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                user = cur.fetchone()
        """
        with cls.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
            finally:
                cursor.close()
    
    @classmethod
    def close_all(cls):
        """Close all connections in the pool."""
        if cls._pool:
            cls._pool.closeall()
            print("[OK] PostgreSQL connection pool closed")


# Initialize on import
PostgresDB.initialize()
