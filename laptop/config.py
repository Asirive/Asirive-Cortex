"""
Configuration for Laptop Server (Tier 2)

Centralizes all configuration settings for the laptop server infrastructure.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# === PATHS ===
LAPTOP_DIR = Path(__file__).parent
PROJECT_ROOT = LAPTOP_DIR.parent
LOGS_DIR = LAPTOP_DIR / "logs"
DATA_DIR = LAPTOP_DIR / "data"

# Create directories if they don't exist
LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# === WEBSOCKET SERVER (RPi ↔ Laptop) ===
WS_SERVER_HOST = os.getenv("WS_SERVER_HOST", "0.0.0.0")  # Listen on all interfaces
WS_SERVER_PORT = int(os.getenv("WS_SERVER_PORT", "8765"))
WS_MAX_CLIENTS = int(os.getenv("WS_MAX_CLIENTS", "5"))  # Max simultaneous RPi connections
WS_PING_INTERVAL = int(os.getenv("WS_PING_INTERVAL", "30"))  # Heartbeat every 30s
WS_PING_TIMEOUT = int(os.getenv("WS_PING_TIMEOUT", "10"))  # Timeout after 10s

# === FASTAPI REST/WEBSOCKET (Laptop ↔ Companion App) ===
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_RELOAD = os.getenv("API_RELOAD", "false").lower() == "true"

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# CORS Configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")  # Comma-separated list
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["*"]
CORS_ALLOW_HEADERS = ["*"]

# === PYQT6 GUI ===
GUI_TITLE = "Project-Cortex v2.0 - Laptop Monitor"
GUI_WIDTH = 1920
GUI_HEIGHT = 1080
GUI_VIDEO_FPS = 30  # Target FPS for video display
GUI_METRICS_UPDATE_RATE = 10  # Update metrics every 100ms

# Video Feed Settings
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_QUALITY = 90  # JPEG quality (0-100)

# === LOGGING ===
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = LOGS_DIR / "cortex_server.log"

# === DATABASE (Future: PostgreSQL + PostGIS for VIO/SLAM) ===
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "cortex_db")
DB_USER = os.getenv("DB_USER", "cortex")
DB_PASSWORD = os.getenv("DB_PASSWORD", "change-me")

# === FEATURE FLAGS ===
ENABLE_VIDEO_RECORDING = os.getenv("ENABLE_VIDEO_RECORDING", "false").lower() == "true"
ENABLE_SLAM_PROCESSING = os.getenv("ENABLE_SLAM_PROCESSING", "false").lower() == "true"
ENABLE_API_SERVER = os.getenv("ENABLE_API_SERVER", "false").lower() == "true"  # Companion app API

# === RATE LIMITING (For FastAPI) ===
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))  # Requests per window
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # Window in seconds

# === DEPLOYMENT (ngrok/Tailscale/Cloudflare) ===
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "local")  # local, ngrok, tailscale, cloudflare
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
TAILSCALE_HOSTNAME = os.getenv("TAILSCALE_HOSTNAME", "cortex-server")
