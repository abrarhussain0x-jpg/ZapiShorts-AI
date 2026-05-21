"""Configuration management — all settings via environment variables with validation."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env and environment variables."""

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    secret_key: str = "change-me-in-production"
    environment: str = "development"  # development | staging | production
    cors_origins: List[str] = ["*"]
    request_id_header: str = "X-Request-ID"

    # ── YouTube ───────────────────────────────────────────────────────────────
    youtube_api_key: str = ""
    youtube_channel_ids: List[str] = []
    youtube_download_quality: str = (
        "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    )
    youtube_rate_limit: int = 100
    youtube_timeout: int = 30
    youtube_retries: int = 3
    youtube_cookies_file: Optional[str] = (
        None  # path to cookies.txt for age-gated content
    )

    # ── Facebook ──────────────────────────────────────────────────────────────
    facebook_access_token: str = ""
    facebook_page_id: str = ""
    facebook_app_id: Optional[str] = None
    facebook_app_secret: Optional[str] = None
    facebook_api_version: str = "v19.0"
    facebook_timeout: int = 120
    facebook_retries: int = 3
    facebook_max_video_size_mb: int = 5120
    facebook_resumable_upload_threshold_mb: int = 100  # use resumable upload above this

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/zapi.db"
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl: int = 86400
    redis_cache_ttl: int = 300  # default endpoint cache TTL

    # ── Video Processing ──────────────────────────────────────────────────────
    max_video_duration_minutes: int = 120
    min_video_duration_minutes: int = 5
    short_video_duration: int = 210
    clip_selection_preset: str = "easy_best"  # easy_best | best | balanced
    max_shorts_per_video: int = 10
    output_resolution: str = "810x1440"  # reduced for 10x faster encoding
    output_fps: int = 24  # reduced for speed
    output_bitrate: str = "1500k"  # 5x lower for ultra-fast encode
    output_codec: str = "libx264"
    output_preset: str = "ultrafast"  # fastest preset
    output_format: str = "mp4"
    audio_normalize: bool = False  # disabled for speed
    audio_target_lufs: float = -14.0  # standard for social video
    add_fade_effects: bool = False  # disabled for speed
    fade_duration_seconds: float = 0.5

    # ── FFmpeg / Hardware Acceleration ────────────────────────────────────────
    ffmpeg_use_hwaccel: bool = True  # enable GPU encoding
    ffmpeg_hwaccel_codec: str = (
        "h264_nvenc"  # h264_nvenc | h264_videotoolbox | h264_amf
    )

    # ── Scene Detection ───────────────────────────────────────────────────────
    scene_detection_threshold: float = 27.0
    scene_detection_enabled: bool = False  # disabled for 50x speed gain
    ffmpeg_scene_detection_timeout_seconds: int = (
        10  # timeout immediately if somehow enabled
    )
    min_segment_duration: int = 15
    max_segment_duration: int = 210  # match short duration

    # ── AI / ML ───────────────────────────────────────────────────────────────
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_whisper_model: str = "whisper-1"
    enable_real_whisper: bool = False  # uses openai whisper when True + key present
    enable_local_whisper: bool = True  # uses faster-whisper (no key required)
    local_whisper_model: str = "base"  # tiny | base | small | medium | large
    caption_style: str = "facebook"
    enable_auto_subtitles: bool = False
    enable_thumbnail_generation: bool = False
    enable_ai_captions: bool = False
    enable_ai_metadata: bool = False  # disabled for speed
    subtitle_font_size: int = 16
    subtitle_color: str = "white"
    subtitle_background: bool = True

    # ── Paths ─────────────────────────────────────────────────────────────────
    data_dir: str = "./data"
    downloads_dir: Optional[str] = None
    output_dir: Optional[str] = None
    logs_dir: Optional[str] = None
    temp_dir: Optional[str] = None

    check_new_videos_interval: int = 3600
    auto_process_enabled: bool = False
    auto_process_interval: int = 86400
    max_concurrent_jobs: int = 4
    job_timeout_minutes: int = 120
    job_retry_max_attempts: int = 3
    job_retry_backoff: float = 2.0

    # ── Logging & Monitoring ──────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"
    log_max_bytes: int = 10_485_760  # 10 MB
    log_backup_count: int = 10
    sentry_dsn: Optional[str] = None
    enable_metrics: bool = True
    metrics_port: int = 8001

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window: int = 60
    slowapi_rate_limit: str = "60/minute"
    max_file_upload_mb: int = 5120
    temp_file_cleanup_hours: int = 24

    # ── Feature Flags ─────────────────────────────────────────────────────────
    enable_batch_processing: bool = True
    enable_analytics: bool = True
    enable_api_docs: bool = True
    enable_webhooks: bool = False
    enable_websocket: bool = True
    admin_ui_enabled: bool = True

    # ── Security ──────────────────────────────────────────────────────────────
    require_api_key: bool = False
    allowed_api_keys: List[str] = []
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # ── Webhooks ──────────────────────────────────────────────────────────────
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.youtube_channel_ids:
            self.youtube_channel_ids = [
                "https://youtube.com/@storylinemovie?si=N7XMWqmBXBSYn9Yw"
            ]
        if not self.downloads_dir:
            self.downloads_dir = os.path.join(self.data_dir, "downloads")
        if not self.output_dir:
            self.output_dir = os.path.join(self.data_dir, "output")
        if not self.logs_dir:
            self.logs_dir = os.path.join(self.data_dir, "logs")
        if not self.temp_dir:
            self.temp_dir = os.path.join(self.data_dir, "temp")

        for d in [self.downloads_dir, self.output_dir, self.logs_dir, self.temp_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

        self._validate_config()

    def _validate_config(self) -> None:
        # Environment overrides
        if self.environment == "testing":
            self.database_url = "sqlite:///:memory:"
            self.redis_url = "redis://localhost:6379/1"

        if self.environment == "production":
            if self.debug:
                raise ValueError("debug must be False in production")
            if self.secret_key == "change-me-in-production":
                raise ValueError("secret_key must be changed in production")
            if not self.youtube_api_key:
                raise ValueError("youtube_api_key required in production")
            if not self.facebook_access_token:
                raise ValueError("facebook_access_token required in production")
            if not self.facebook_page_id:
                raise ValueError("facebook_page_id required in production")

    # ── Convenience getters ───────────────────────────────────────────────────
    def get_database_config(self) -> Dict[str, Any]:
        return {
            "url": self.database_url,
            "pool_size": self.database_pool_size,
            "max_overflow": self.database_max_overflow,
            "pool_timeout": self.database_pool_timeout,
            "pool_recycle": self.database_pool_recycle,
            "echo": self.database_echo,
        }

    def get_redis_config(self) -> Dict[str, Any]:
        return {"url": self.redis_url, "ttl": self.redis_ttl}

    def get_video_config(self) -> Dict[str, Any]:
        return {
            "resolution": self.output_resolution,
            "fps": self.output_fps,
            "bitrate": self.output_bitrate,
            "codec": self.output_codec,
            "preset": self.output_preset,
            "format": self.output_format,
        }

    @property
    def output_width(self) -> int:
        try:
            return int(self.output_resolution.split("x")[0])
        except Exception:
            return 1080

    @property
    def output_height(self) -> int:
        try:
            return int(self.output_resolution.split("x")[1])
        except Exception:
            return 1920


settings = Settings()
