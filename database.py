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
    """Centralized database operations with improved error handling"""
    
    DB_NAME = 'bot.db'
    
    @classmethod
    def _get_connection(cls):
        """Establish database connection with proper settings"""
        conn = sqlite3.connect(cls.DB_NAME)  # استفاده از cls.DB_NAME
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    @staticmethod
    def execute_query(
        query: str, 
        params: tuple = (), 
        fetch_one: bool = False
    ) -> Union[List[Dict[str, Any]], Dict[str, Any], None]:
        """Execute a read query with proper error handling"""
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
        """Get the current week from database"""
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
        """Set the current week in database"""
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                conn.execute(f"PRAGMA user_version = {week}")
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error setting current week: {e}")
            return False

    @staticmethod
    def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
                row = cur.fetchone()
                return row[0] if row else default
        except Exception:
            return default

    @staticmethod
    def set_setting(key: str, value: str) -> bool:
        try:
            with closing(DatabaseManager._get_connection()) as conn:
                conn.execute("""
                    INSERT INTO settings(key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                """, (key, value))
                conn.commit()
                return True
        except Exception:
            return False

    @staticmethod
    def lock_week(week: int) -> bool:
        return DatabaseManager.set_setting(f"lock_week_{week}", "1")

    @staticmethod
    def unlock_week(week: int) -> bool:
        return DatabaseManager.set_setting(f"lock_week_{week}", "0")

    @staticmethod
    def is_week_locked(week: int) -> bool:
        return DatabaseManager.get_setting(f"lock_week_{week}", "0") == "1"

    @staticmethod
    def get_user_predictions(user_id: int, week: Optional[int] = None) -> List[Dict]:
        """Get user predictions with optional week filter"""
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
        """ایجاد جداول اولیه پایگاه داده"""
        try:
            with sqlite3.connect(DatabaseManager.DB_NAME) as conn:
                cursor = conn.cursor()
                
                # ایجاد جدول کاربران
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    username TEXT,
                    language_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                
                # ایجاد جدول مسابقات
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
                
                # ایجاد جدول پیش‌بینی‌ها با ساختار اصلاح شده
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
                
                # ایجاد جدول تنظیمات
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                
                # تنظیم هفته جاری
                cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) 
                VALUES ('current_week', '1')
                """)
                
                conn.commit()
                logger.info("پایگاه داده با موفقیت راه‌اندازی شد")
                
        except sqlite3.Error as e:
            logger.error(f"خطا در راه‌اندازی پایگاه داده: {e}")
            raise



