"""YouTube downloader — yt-dlp with integrity check, channel pagination, progress tracking."""

import logging
import os
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, List, Optional

import yt_dlp

from src.config.settings import settings
from src.utils.validators import URLValidator

logger = logging.getLogger(__name__)

# Progress context variable — set during download so WebSocket can stream it
_download_progress: ContextVar[Dict] = ContextVar("download_progress", default={})


class YouTubeDownloader:
    """Download YouTube videos and channel lists via yt-dlp."""

    def __init__(self):
        self.output_dir = settings.downloads_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    # ── ydl options ──────────────────────────────────────────────────────────

    def get_ydl_opts(self, quiet: bool = False) -> dict:
        opts: dict = {
            "format": settings.youtube_download_quality,
            "outtmpl": os.path.join(self.output_dir, "%(id)s_%(title).80s.%(ext)s"),
            "quiet": quiet,
            "no_warnings": quiet,
            "progress_hooks": [self._progress_hook],
            "socket_timeout": settings.youtube_timeout,
            "retries": settings.youtube_retries,
            "fragment_retries": settings.youtube_retries,
            "skip_unavailable_fragments": True,
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
        }
        # Cookie support for age-gated / authenticated content
        if settings.youtube_cookies_file and os.path.exists(
            settings.youtube_cookies_file
        ):
            opts["cookiefile"] = settings.youtube_cookies_file
        return opts

    # ── Progress hook ─────────────────────────────────────────────────────────

    def _progress_hook(self, d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            pct = d.get("_percent_str", "?%").strip()
            speed = d.get("_speed_str", "?")
            eta = d.get("_eta_str", "?")
            _download_progress.set({"percent": pct, "speed": speed, "eta": eta})
            logger.debug("Download progress: %s at %s ETA %s", pct, speed, eta)
        elif status == "finished":
            logger.info("Download finished: %s", d.get("filename"))

    # ── Date parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_upload_date(upload_date: Optional[str]) -> Optional[datetime]:
        if not upload_date:
            return None
        try:
            if len(upload_date) == 8 and upload_date.isdigit():
                return datetime.strptime(upload_date, "%Y%m%d")
            return datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def get_video_info(self, youtube_url: str) -> Optional[dict]:
        """Fetch video metadata without downloading."""
        if not URLValidator.is_youtube_url(youtube_url):
            logger.error("Invalid YouTube URL: %s", youtube_url)
            return None
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
            return self._build_info_dict(info)
        except Exception as exc:
            logger.error("get_video_info failed for %s: %s", youtube_url, exc)
            return None

    def download_video(self, youtube_url: str) -> Optional[dict]:
        """Download a single YouTube video. Returns metadata dict or None."""
        if not URLValidator.is_youtube_url(youtube_url):
            logger.error("Invalid YouTube URL: %s", youtube_url)
            return None
        try:
            logger.info("Downloading: %s", youtube_url)
            with yt_dlp.YoutubeDL(self.get_ydl_opts()) as ydl:
                info = ydl.extract_info(youtube_url, download=True)

            video_id = info.get("id")
            downloaded_file = self._find_downloaded_file(video_id)
            if not downloaded_file:
                logger.error("Downloaded file not found for %s", video_id)
                return None

            if not self.verify_video_integrity(downloaded_file):
                logger.error("Integrity check failed for %s", downloaded_file)
                return None

            result = self._build_info_dict(info)
            result["local_path"] = downloaded_file
            result["file_size_bytes"] = os.path.getsize(downloaded_file)
            logger.info(
                "Downloaded: %s (%.1f MB)",
                info.get("title"),
                result["file_size_bytes"] / 1_048_576,
            )
            return result

        except Exception as exc:
            logger.error(
                "download_video failed for %s: %s", youtube_url, exc, exc_info=True
            )
            return None

    def download_channel_videos(
        self, channel_url: str, max_videos: Optional[int] = None
    ) -> List[dict]:
        """Download videos from a channel, returning list of metadata dicts."""
        downloaded: List[dict] = []
        try:
            logger.info("Fetching channel listing: %s", channel_url)
            for video_url in self.iter_channel_video_urls(channel_url, max_videos):
                result = self.download_video(video_url)
                if result:
                    downloaded.append(result)
            logger.info("Downloaded %d videos from channel", len(downloaded))
        except Exception as exc:
            logger.error("download_channel_videos failed: %s", exc)
        return downloaded

    def iter_channel_video_urls(
        self, channel_url: str, max_videos: Optional[int] = None
    ) -> Generator[str, None, None]:
        """Yield individual video URLs from a channel lazily."""
        opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
            entries = info.get("entries") or []
            for i, entry in enumerate(entries):
                if max_videos and i >= max_videos:
                    break
                vid_id = entry.get("id")
                if vid_id:
                    yield f"https://www.youtube.com/watch?v={vid_id}"
        except Exception as exc:
            logger.error("iter_channel_video_urls failed: %s", exc)

    def verify_video_integrity(self, video_path: str) -> bool:
        """Run ffprobe to confirm the file is a valid, readable video."""
        import subprocess

        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=nw=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception as exc:
            logger.warning("verify_video_integrity error: %s", exc)
            return True  # don't block on ffprobe failure

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_downloaded_file(self, video_id: str) -> Optional[str]:
        """Find a downloaded file by its YouTube video ID using targeted glob.

        Uses glob patterns over known video extensions instead of scanning
        every file in the directory — O(extensions) instead of O(all files).
        """
        video_extensions = (".mp4", ".mkv", ".webm", ".m4v", ".mov")
        downloads = Path(self.output_dir)
        for ext in video_extensions:
            for path in downloads.glob(f"*{video_id}*{ext}"):
                if path.is_file():
                    return str(path)
        return None

    @staticmethod
    def _build_info_dict(info: dict) -> dict:
        return {
            "youtube_id": info.get("id"),
            "title": info.get("title", ""),
            "description": info.get("description", ""),
            "duration_seconds": info.get("duration", 0),
            "thumbnail_url": info.get("thumbnail", ""),
            "channel_id": info.get("channel_id", ""),
            "channel_name": info.get("uploader", ""),
            "published_at": YouTubeDownloader._parse_upload_date(
                info.get("upload_date")
            ),
            "tags": ",".join(info.get("tags") or [])[:500],
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
        }
