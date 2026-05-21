"""Environment and readiness checks for ZAPI."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def check_python_version() -> bool:
    """Check Python version."""
    logger.info("Checking Python version...")
    if sys.version_info < (3, 11):
        logger.error(
            "Python 3.11+ required, found %s.%s",
            sys.version_info.major,
            sys.version_info.minor,
        )
        return False
    logger.info("✓ Python %s.%s", sys.version_info.major, sys.version_info.minor)
    return True


def check_env_file() -> bool:
    """Check if .env file exists."""
    logger.info("Checking .env file...")
    if os.path.exists(".env"):
        logger.info("✓ .env file exists")
        return True

    logger.warning(".env file not found. Creating from template...")
    if os.path.exists(".env.example"):
        shutil.copy(".env.example", ".env")
        logger.info(
            "✓ .env created from template (please update with your credentials)"
        )
    return False


def check_dependencies() -> bool:
    """Check if required packages are installed."""
    logger.info("Checking Python dependencies...")
    required = ["fastapi", "sqlalchemy", "yt_dlp", "cv2", "numpy"]

    missing: list[str] = []
    for package in required:
        try:
            __import__(package)
            logger.info("✓ %s", package)
        except ImportError:
            logger.error("✗ %s missing", package)
            missing.append(package)

    if missing:
        logger.error("Missing packages: %s", ", ".join(missing))
        logger.error("Run: pip install -r requirements.txt")
        return False

    return True


def check_system_tools() -> bool:
    """Check if system tools are available."""
    logger.info("Checking system tools...")

    tools = {
        "ffmpeg": "FFmpeg",
        "ffprobe": "FFprobe",
        "psql": "PostgreSQL client",
    }

    available = True
    for cmd, name in tools.items():
        try:
            result = subprocess.run(
                [cmd, "--version"], capture_output=True, timeout=5, check=False
            )
            if result.returncode == 0:
                logger.info("✓ %s", name)
            else:
                logger.warning("⚠ %s (may not be working)", name)
        except FileNotFoundError:
            logger.warning("✗ %s not found", name)
            available = False

    return available


def check_env_variables() -> bool:
    """Check if required environment variables are set."""
    logger.info("Checking environment variables...")
    load_dotenv()

    required = ["DATABASE_URL"]
    missing: list[str] = []

    for var in required:
        if os.getenv(var):
            logger.info("✓ %s set", var)
        else:
            logger.warning("✗ %s not set", var)
            missing.append(var)

    if missing:
        logger.warning("Missing variables: %s", ", ".join(missing))
        logger.warning("Update .env file with your credentials")
        return False

    return True


def check_directories() -> bool:
    """Create required directories."""
    logger.info("Checking directories...")

    dirs = ["data", "data/downloads", "data/output", "data/logs"]
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        logger.info("✓ %s", dir_path)

    return True


def _run_checks(
    checks: Iterable[tuple[str, Callable[[], bool]]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for name, check_func in checks:
        logger.info("%s:", name)
        logger.info("%s", "-" * 40)
        try:
            result = check_func()
            results.append({"check": name, "passed": result})
        except Exception as exc:
            logger.error("Error: %s", exc)
            results.append({"check": name, "passed": False, "error": str(exc)})
    return results


def main() -> int:
    """Run all setup checks."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    logger.info("%s", "=" * 50)
    logger.info("ZAPI Setup Verification")
    logger.info("%s", "=" * 50)
    logger.info("")

    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("System Tools", check_system_tools),
        ("Environment File", check_env_file),
        ("Environment Variables", check_env_variables),
        ("Directories", check_directories),
    ]

    results = _run_checks(checks)

    logger.info("%s", "\n" + "=" * 50)
    logger.info("Setup Summary")
    logger.info("%s", "=" * 50)

    for item in results:
        status = "✓" if item["passed"] else "✗"
        logger.info("%s %s", status, item["check"])

    passed = all(item["passed"] for item in results)

    logger.info("%s", "\n" + "=" * 50)
    if passed:
        logger.info("✓ All checks passed! Ready to start.")
        logger.info("Next steps:")
        logger.info("1. Start PostgreSQL & Redis")
        logger.info("2. Run: python cli.py init-db")
        logger.info("3. Run: uvicorn src.api.main:app --reload")
        logger.info("4. Visit: http://localhost:8000/docs")
        return 0

    logger.error("✗ Some checks failed. Please fix the issues above.")
    logger.error("Docker alternative:")
    logger.error("docker-compose up -d")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
