"""
File Utilities
Safe file handling with validation, temporary storage, and cleanup
"""
import os
import uuid
import logging
import tempfile
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def validate_file_extension(filename: str) -> bool:
    """Check that the file has an allowed extension."""
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in settings.allowed_extensions_list


def validate_file_size(file_bytes: bytes) -> bool:
    """Check that the file size is within limits."""
    return len(file_bytes) <= settings.max_file_size_bytes


def save_temp_file(file_bytes: bytes, original_filename: str) -> str:
    """
    Save uploaded file bytes to a temporary location.
    Returns the temp file path.
    Privacy: temp files should be deleted after processing.
    """
    temp_dir = Path(settings.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(original_filename).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    temp_path = temp_dir / unique_name

    with open(temp_path, "wb") as f:
        f.write(file_bytes)

    logger.debug(f"Temp file saved: {temp_path.name}")  # Log name only, not contents
    return str(temp_path)


def delete_temp_file(file_path: str) -> None:
    """
    Delete a temporary file after processing.
    Privacy: remove resume data from disk.
    """
    try:
        path = Path(file_path)
        if path.exists():
            path.unlink()
            logger.debug(f"Temp file deleted: {path.name}")
    except Exception as e:
        logger.warning(f"Failed to delete temp file: {e}")


def get_safe_filename(filename: str) -> str:
    """Sanitize a filename to prevent directory traversal."""
    safe = Path(filename).name  # Remove any directory components
    # Replace potentially problematic characters
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in safe)
    return safe[:100]  # Limit length


def cleanup_old_temp_files(max_age_minutes: int = 60) -> int:
    """Remove temp files older than max_age_minutes. Returns count deleted."""
    import time
    temp_dir = Path(settings.temp_dir)
    if not temp_dir.exists():
        return 0

    deleted = 0
    cutoff = time.time() - (max_age_minutes * 60)

    for f in temp_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass

    if deleted:
        logger.info(f"Cleaned up {deleted} old temp files")
    return deleted
