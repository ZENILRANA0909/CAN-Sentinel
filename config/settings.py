from pathlib import Path

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Project Folders
LOG_DIR = BASE_DIR / "logs"
MODEL_DIR = BASE_DIR / "models"
DATASET_DIR = BASE_DIR / "datasets"
REPORT_DIR = BASE_DIR / "reports"
EXPORT_DIR = BASE_DIR / "exports"

# Create folders automatically
for directory in [
    LOG_DIR,
    MODEL_DIR,
    DATASET_DIR,
    REPORT_DIR,
    EXPORT_DIR,
]:
    directory.mkdir(exist_ok=True)

# CAN Configuration
CAN_INTERFACE = "virtual"   # macOS development
CAN_CHANNEL = None

# Application
APP_NAME = "CAN-Sentinel"
APP_VERSION = "1.0.0"

# Database
DATABASE_NAME = "can_sentinel.db"

# CSV Log
CSV_LOG_FILE = LOG_DIR / "can_log.csv"