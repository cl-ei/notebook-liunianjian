import os
import sys
from pathlib import Path

RESERVED_EMAIL = "guest@madliar.com"

IS_PROD = os.environ.get("RUN_ENV", "") == "prod"

DEBUG = not IS_PROD
if DEBUG:
    print("The app is running in DEBUG mode.")

if DEBUG:
    LOG_FILE = str(Path.home() / "notebook_app.log")
else:
    LOG_FILE = os.environ.get("LOG_FILE")
    if not LOG_FILE:
        LOG_FILE = "/var/logs/notebook_app.log"
print(f"APP log will be written to this file: {LOG_FILE}")

STORAGE_ROOT = os.environ.get("STORAGE_ROOT")
if not STORAGE_ROOT:
    STORAGE_ROOT = str(Path.home() / "notebook_storage_root")
    print(f"No STORAGE_ROOT configured, storage root dir will be set as: {STORAGE_ROOT}")
