"""Multi-platform publishing profiles for short-form content."""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    width: int
    height: int
    fps: int
    bitrate: str
    codec: str = "libx264"
    format: str = "mp4"


PLATFORM_PROFILES: Dict[str, PlatformProfile] = {
    "facebook_reels": PlatformProfile("facebook_reels", 1080, 1920, 30, "8000k"),
    "instagram_reels": PlatformProfile("instagram_reels", 1080, 1920, 30, "8000k"),
    "tiktok": PlatformProfile("tiktok", 1080, 1920, 30, "6000k"),
    "youtube_shorts": PlatformProfile("youtube_shorts", 1080, 1920, 30, "10000k"),
}

PLATFORM_ALIASES: Dict[str, str] = {
    "facebook": "facebook_reels",
    "instagram": "instagram_reels",
    "youtube": "youtube_shorts",
    "yt": "youtube_shorts",
    "shorts": "youtube_shorts",
}


def _normalize_platform_name(name: str) -> str:
    key = (name or "").strip().lower()
    return PLATFORM_ALIASES.get(key, key)


def normalize_platform_name(name: str) -> str:
    return _normalize_platform_name(name)


def resolve_profiles(requested: List[str] | None) -> List[PlatformProfile]:
    if not requested:
        return [
            PLATFORM_PROFILES["facebook_reels"],
            PLATFORM_PROFILES["instagram_reels"],
            PLATFORM_PROFILES["tiktok"],
            PLATFORM_PROFILES["youtube_shorts"],
        ]

    profiles: List[PlatformProfile] = []
    for name in requested:
        key = _normalize_platform_name(name)
        if key in PLATFORM_PROFILES:
            profiles.append(PLATFORM_PROFILES[key])

    return profiles or [PLATFORM_PROFILES["facebook_reels"]]


def validate_platform_names(requested: List[str] | None) -> Tuple[List[str], List[str]]:
    normalized: List[str] = []
    invalid: List[str] = []

    for name in requested or []:
        key = _normalize_platform_name(name)
        if key in PLATFORM_PROFILES:
            normalized.append(key)
        elif key:
            invalid.append(name)

    return normalized, invalid


def is_supported_platform(name: str) -> bool:
    return normalize_platform_name(name) in PLATFORM_PROFILES
