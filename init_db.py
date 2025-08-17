import sqlite3
import json
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "bot.db"
MATCHES_JSON_PATH = Path(__file__).parent / "matches_data.json"

def create_tables(conn):
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS matches")
    cursor.execute("DROP TABLE IF EXISTS predictions")
    cursor.execute("DROP TABLE IF EXISTS users")
    
    cursor.execute('''
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY,
            week INTEGER NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            result TEXT,
            played BOOLEAN DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            username TEXT,
            language_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE predictions (
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
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(match_id) REFERENCES matches(id),
            UNIQUE(user_id, match_id)
        )
    ''')
    
    conn.commit()
    logger.info("Tables created successfully")

def import_matches(conn):
    if not MATCHES_JSON_PATH.exists():
        logger.error(f"Matches file not found at {MATCHES_JSON_PATH}")
        return False

    with open(MATCHES_JSON_PATH, "r", encoding="utf-8") as f:
        all_weeks = json.load(f)

    cursor = conn.cursor()
    imported = 0

    for week_key, matches in all_weeks.items():
        try:
            week_number = int(week_key.split('_')[-1])
        except Exception as e:
            logger.warning(f"Invalid week key format: {week_key}, error: {e}")
            continue

        for game in matches:
            try:
                cursor.execute(
                    "INSERT INTO matches (id, week, home_team, away_team, result) VALUES (?, ?, ?, ?, ?)",
                    (game['id'], week_number, game['home'], game['away'], game.get('result'))
                )
                imported += 1
            except Exception as e:
                logger.error(f"Failed to import game {game['id']}: {e}")
                continue

    conn.commit()
    logger.info(f"Successfully imported {imported} matches")
    return True

def init_db():
    try:
        if DB_PATH.exists():
            DB_PATH.unlink()
            
        conn = sqlite3.connect(DB_PATH)
        create_tables(conn)
        
        if not import_matches(conn):
            raise Exception("Match import failed")
            
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        
        logger.info(f"Database initialized successfully at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    init_db()