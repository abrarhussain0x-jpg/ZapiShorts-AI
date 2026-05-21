"""File system utilities — cleanup, size reporting, safe I/O."""

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


def cleanup_old_files(directory: str, max_age_hours: float = 24) -> int:
    """Delete files older than *max_age_hours* in *directory*. Returns count removed."""
    removed = 0
    cutoff = time.time() - (max_age_hours * 3600)
    path = Path(directory)
    if not path.exists():
        return 0
    for item in path.iterdir():
        if item.is_file() and item.stat().st_mtime < cutoff:
            try:
                item.unlink()
                removed += 1
                logger.debug("Deleted stale file: %s", item)
            except OSError as exc:
                logger.warning("Could not delete %s: %s", item, exc)
    return removed


def get_directory_size(directory: str) -> int:
    """Return total bytes used by all files in *directory* (recursive)."""
    total = 0
    for root, _, files in os.walk(directory):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def get_directory_info(directory: str) -> Dict:
    """Return a dict with total_bytes, total_gb, file_count."""
    total = get_directory_size(directory)
    count = sum(len(files) for _, _, files in os.walk(directory))
    return {
        "total_bytes": total,
        "total_gb": round(total / (1024**3), 4),
        "file_count": count,
    }


def safe_delete(path: str) -> bool:
    """Delete a file without raising if it doesn't exist."""
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
        return True
    except OSError as exc:
        logger.warning("safe_delete failed for %s: %s", path, exc)
        return False


def ensure_dirs(*paths: str) -> None:
    """Create directories atomically, no-op if already existing."""
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def move_file(src: str, dst: str) -> bool:
    """Move a file, creating destination directory if needed."""
    try:
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        return True
    except Exception as exc:
        logger.error("move_file failed %s → %s: %s", src, dst, exc)
        return False


def list_files_by_extension(directory: str, *extensions: str) -> List[str]:
    """Return absolute paths of all files matching given extensions."""
    result = []
    ext_set = {e.lower().lstrip(".") for e in extensions}
    for root, _, files in os.walk(directory):
        for f in files:
            if Path(f).suffix.lstrip(".").lower() in ext_set:
                result.append(os.path.join(root, f))
    return result


def format_file_size(size_bytes: int) -> str:
    """Return human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
