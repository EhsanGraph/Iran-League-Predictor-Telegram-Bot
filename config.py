import os
from dotenv import load_dotenv
from database import DatabaseManager
from typing import List, Dict, Optional
import sqlite3
from contextlib import closing
import logging



# Configure logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
raw_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x) for x in raw_admins.split(",") if x.strip().isdigit()]

# Game settings
DEFAULT_SCORES = ["1-0", "2-1", "3-1", "0-0"]
MAX_SCORE_LENGTH = 7
POINTS_FOR_EXACT_SCORE = 5
POINTS_FOR_CORRECT_WINNER = 3
POINTS_FOR_PARTIAL_SCORE = 1
