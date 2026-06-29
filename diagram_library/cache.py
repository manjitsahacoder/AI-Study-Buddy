from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc)


def cache_file_exists(static_folder, image_path):
    if not image_path:
        return False
    return (Path(static_folder) / image_path).exists()
