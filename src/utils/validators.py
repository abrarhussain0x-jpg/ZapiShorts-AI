"""Validation and utility functions"""

import os
import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from src.utils.exceptions import ValidationError


class URLValidator:
    """Validate URLs"""

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        """Check if URL is valid YouTube URL"""
        youtube_regex = (
            r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/"
        )
        return bool(re.match(youtube_regex, url))

    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extract YouTube video ID from URL"""
        if not URLValidator.is_youtube_url(url):
            raise ValidationError(f"Invalid YouTube URL: {url}")

        patterns = [
            r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)",
            r"youtube\.com\/watch\?.*&v=([^&\n?#]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        raise ValidationError(f"Could not extract video ID from: {url}")

    @staticmethod
    def extract_channel_url(url: str) -> str:
        """Extract channel URL"""
        if "youtube.com/c/" in url:
            return url.split("?")[0]
        if "youtube.com/@" in url:
            return url.split("?")[0]
        if "youtube.com/channel/" in url:
            return url.split("?")[0]
        raise ValidationError(f"Invalid YouTube channel URL: {url}")


class FileValidator:
    """Validate files"""

    @staticmethod
    def validate_video_path(path: str) -> bool:
        """Validate video file exists and is readable"""
        if not os.path.exists(path):
            raise ValidationError(f"Video file not found: {path}")

        if not os.path.isfile(path):
            raise ValidationError(f"Path is not a file: {path}")

        if not os.access(path, os.R_OK):
            raise ValidationError(f"Video file not readable: {path}")

        # Check if file has content
        if os.path.getsize(path) == 0:
            raise ValidationError(f"Video file is empty: {path}")

        return True

    @staticmethod
    def validate_output_path(path: str) -> bool:
        """Validate output path is writable"""
        directory = os.path.dirname(path)

        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except Exception as e:
                raise ValidationError(f"Cannot create output directory: {str(e)}")

        if directory and not os.access(directory, os.W_OK):
            raise ValidationError(f"Output directory not writable: {directory}")

        return True

    @staticmethod
    def get_file_size_mb(path: str) -> float:
        """Get file size in MB"""
        try:
            return os.path.getsize(path) / (1024 * 1024)
        except Exception as e:
            raise ValidationError(f"Cannot get file size: {str(e)}")


class VideoValidator:
    """Validate video properties"""

    @staticmethod
    def validate_duration(duration_seconds: int) -> bool:
        """Validate video duration"""
        from src.config.settings import settings

        min_duration = settings.min_video_duration_minutes * 60
        max_duration = settings.max_video_duration_minutes * 60

        if duration_seconds < min_duration:
            raise ValidationError(
                f"Video too short: {duration_seconds}s (minimum: {min_duration}s)"
            )

        if duration_seconds > max_duration:
            raise ValidationError(
                f"Video too long: {duration_seconds}s (maximum: {max_duration}s)"
            )

        return True

    @staticmethod
    def validate_resolution(width: int, height: int) -> bool:
        """Validate video resolution"""
        if width < 640 or height < 360:
            raise ValidationError(
                f"Video resolution too low: {width}x{height} (minimum: 640x360)"
            )

        if width > 4096 or height > 4096:
            raise ValidationError(
                f"Video resolution too high: {width}x{height} (maximum: 4096x4096)"
            )

        return True


class StringValidator:
    """Validate strings"""

    @staticmethod
    def validate_title(title: str, min_length: int = 3, max_length: int = 255) -> bool:
        """Validate title"""
        if not title:
            raise ValidationError("Title cannot be empty")

        if len(title) < min_length:
            raise ValidationError(f"Title too short (minimum: {min_length} characters)")

        if len(title) > max_length:
            raise ValidationError(f"Title too long (maximum: {max_length} characters)")

        return True

    @staticmethod
    def validate_description(description: str, max_length: int = 5000) -> bool:
        """Validate description"""
        if description and len(description) > max_length:
            raise ValidationError(
                f"Description too long (maximum: {max_length} characters)"
            )

        return True

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename"""
        # Remove invalid characters
        invalid_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(invalid_chars, "_", filename)
        # Remove leading/trailing spaces and dots
        sanitized = sanitized.strip(". ")
        # Limit length
        if len(sanitized) > 200:
            sanitized = sanitized[:200]
        return sanitized


class NumberValidator:
    """Validate numbers"""

    @staticmethod
    def validate_percentage(value: float) -> bool:
        """Validate percentage (0-100)"""
        if not isinstance(value, (int, float)):
            raise ValidationError("Percentage must be a number")

        if value < 0 or value > 100:
            raise ValidationError(f"Percentage must be between 0 and 100: {value}")

        return True

    @staticmethod
    def validate_positive_integer(value: int, name: str = "value") -> bool:
        """Validate positive integer"""
        if not isinstance(value, int):
            raise ValidationError(f"{name} must be an integer")

        if value <= 0:
            raise ValidationError(f"{name} must be positive: {value}")

        return True


def validate_all(validators: List[tuple]) -> bool:
    """Run multiple validators"""
    for validator_func, *args in validators:
        try:
            validator_func(*args)
        except ValidationError:
            raise
    return True
