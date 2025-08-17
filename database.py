import sqlite3
import logging
from contextlib import closing
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class DatabaseManager:    
    DB_NAME = 'bot.db'
    
    @classmethod
    def _get_connection(cls):
        conn = sqlite3.connect(cls.DB_NAME)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    @staticmethod
    def execute_query(
        query: str, 
        params: tuple = (), 
        fetch_one: bool = False
    ) -> Union[List[Dict[str, Any]], Dict[str, Any], None]:
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                with closing(conn.cursor()) as cur:
                    cur.execute(query, params)
                    return cur.fetchone() if fetch_one else cur.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Database error in query '{query}': {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in query execution: {e}")
            raise

    @staticmethod
    def get_current_week() -> int:
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA user_version")
                result = cursor.fetchone()
                return result[0] if result and result[0] > 0 else 1
        except Exception as e:
            logger.error(f"Error getting current week: {e}")
            return 1

    @staticmethod
    def set_current_week(week: int) -> bool:
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                conn.execute(f"PRAGMA user_version = {week}")
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting current week: {e}")
            return False

    @staticmethod
    def get_user_predictions(user_id: int, week: Optional[int] = None) -> List[Dict]:
        query = """
            SELECT p.*, m.home_team, m.away_team, m.result 
            FROM predictions p
            JOIN matches m ON p.match_id = m.id
            WHERE p.user_id = ?
        """
        params = [user_id]
        
        if week:
            query += " AND p.week = ?"
            params.append(week)
            
        query += " ORDER BY p.week, p.match_id"
        
        return DatabaseManager.execute_query(query, tuple(params))

    @staticmethod
    def execute_write(query: str, params: tuple = ()) -> bool:
        try:
            with sqlite3.connect(DatabaseManager.DB_NAME) as conn:  # استفاده از DB_NAME
                conn.execute(query, params)
                conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Database write error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in execute_write: {e}")
            return False

    @staticmethod
    def initialize_database():
        try:
            with sqlite3.connect(DatabaseManager.DB_NAME) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    username TEXT,
                    language_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week INTEGER NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    match_id INTEGER NOT NULL,
                    week INTEGER NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    score TEXT NOT NULL,
                    winner TEXT NOT NULL,
                    points INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (match_id) REFERENCES matches(id),
                    UNIQUE(user_id, match_id)
                )""")
                
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                
                cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('current_week', '1')
                """)
                
                conn.commit()
                logger.info("پایگاه داده با موفقیت راه‌اندازی شد")
                
        except sqlite3.Error as e:
            logger.error(f"خطا در راه‌اندازی پایگاه داده: {e}")
            raise