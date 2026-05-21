"""Facebook uploader — standard + resumable upload, async variant, retry, token validation."""

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
import requests
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from src.config.settings import settings

logger = logging.getLogger(__name__)

_GRAPH = f"https://graph.facebook.com/{settings.facebook_api_version}"
_RESUMABLE_THRESHOLD = settings.facebook_resumable_upload_threshold_mb * 1_048_576


class FacebookUploader:
    """Upload videos to Facebook with standard or resumable upload, retry, and token checks."""

    def __init__(self):
        self.access_token = settings.facebook_access_token
        self.page_id = settings.facebook_page_id
        self.api_version = settings.facebook_api_version
        self.graph = f"https://graph.facebook.com/{self.api_version}"

    # ── Token validation ──────────────────────────────────────────────────────

    def validate_token(self) -> bool:
        """Call /me to confirm the token is valid."""
        if not self.access_token:
            return False
        try:
            r = requests.get(
                f"{self.graph}/me",
                params={"access_token": self.access_token, "fields": "id,name"},
                timeout=15,
            )
            return r.status_code == 200
        except Exception as exc:
            logger.warning("Token validation failed: %s", exc)
            return False

    # ── Upload dispatcher ─────────────────────────────────────────────────────

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        schedule_time: Optional[datetime] = None,
        is_reels: bool = True,
    ) -> Optional[str]:
        """Upload to Facebook — uses resumable protocol for large files."""
        if not self.access_token or not self.page_id:
            logger.error("Facebook credentials not configured")
            return None
        if not os.path.exists(video_path):
            logger.error("Video file not found: %s", video_path)
            return None

        file_size = os.path.getsize(video_path)
        if file_size > settings.facebook_max_video_size_mb * 1_048_576:
            logger.error("File too large: %.0f MB", file_size / 1_048_576)
            return None

        if file_size >= _RESUMABLE_THRESHOLD:
            return self._resumable_upload(
                video_path, title, description, schedule_time, is_reels
            )
        return self._simple_upload(
            video_path, title, description, schedule_time, is_reels
        )

    # ── Simple upload ─────────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def _simple_upload(
        self,
        video_path: str,
        title: str,
        description: str,
        schedule_time: Optional[datetime],
        is_reels: bool,
    ) -> Optional[str]:
        endpoint = (
            f"{self.graph}/{self.page_id}/{'video_reels' if is_reels else 'videos'}"
        )
        data: Dict[str, Any] = {
            "access_token": self.access_token,
            "title": title[:255],
            "description": description[:2000],
        }
        if schedule_time:
            data["scheduled_publish_time"] = int(schedule_time.timestamp())
            data["published"] = "false"
        else:
            data["published"] = "true"

        logger.info(
            "Simple upload → %s (%.1f MB)",
            title[:60],
            os.path.getsize(video_path) / 1_048_576,
        )
        with open(video_path, "rb") as f:
            resp = requests.post(
                endpoint,
                data=data,
                files={"file": f},
                timeout=settings.facebook_timeout,
            )
        if resp.status_code in (200, 201):
            result = resp.json()
            video_id = result.get("video_id") or result.get("id")
            logger.info("Upload succeeded: video_id=%s", video_id)
            return video_id
        logger.error("Upload failed %d: %s", resp.status_code, resp.text[:300])
        return None

    # ── Resumable upload ──────────────────────────────────────────────────────

    def _resumable_upload(
        self,
        video_path: str,
        title: str,
        description: str,
        schedule_time: Optional[datetime],
        is_reels: bool,
    ) -> Optional[str]:
        """Facebook chunked resumable upload for files ≥ threshold."""
        file_size = os.path.getsize(video_path)
        logger.info("Resumable upload: %s (%.1f MB)", title[:60], file_size / 1_048_576)

        try:
            # Phase 1 — initialise session
            init_resp = requests.post(
                f"{self.graph}/{self.page_id}/videos",
                data={
                    "access_token": self.access_token,
                    "upload_phase": "start",
                    "file_size": file_size,
                },
                timeout=30,
            )
            if init_resp.status_code != 200:
                logger.error("Resumable init failed: %s", init_resp.text[:200])
                return None
            session_data = init_resp.json()
            upload_session_id = session_data.get("upload_session_id")
            start_offset = int(session_data.get("start_offset", 0))
            end_offset = int(session_data.get("end_offset", file_size))

            # Phase 2 — transfer chunks
            chunk_size = 10 * 1_048_576  # 10 MB chunks
            with open(video_path, "rb") as f:
                while start_offset < file_size:
                    f.seek(start_offset)
                    chunk = f.read(min(chunk_size, end_offset - start_offset))
                    transfer_resp = requests.post(
                        f"{self.graph}/{self.page_id}/videos",
                        data={
                            "access_token": self.access_token,
                            "upload_phase": "transfer",
                            "upload_session_id": upload_session_id,
                            "start_offset": start_offset,
                        },
                        files={"video_file_chunk": chunk},
                        timeout=120,
                    )
                    if transfer_resp.status_code != 200:
                        logger.error(
                            "Chunk transfer failed: %s", transfer_resp.text[:200]
                        )
                        return None
                    offsets = transfer_resp.json()
                    start_offset = int(offsets.get("start_offset", file_size))
                    end_offset = int(offsets.get("end_offset", file_size))
                    pct = start_offset / file_size * 100
                    logger.debug("Upload progress: %.1f%%", pct)

            # Phase 3 — finalise
            finish_data: Dict[str, Any] = {
                "access_token": self.access_token,
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "title": title[:255],
                "description": description[:2000],
            }
            if schedule_time:
                finish_data["scheduled_publish_time"] = int(schedule_time.timestamp())
                finish_data["published"] = "false"
            else:
                finish_data["published"] = "true"

            finish_resp = requests.post(
                f"{self.graph}/{self.page_id}/videos",
                data=finish_data,
                timeout=60,
            )
            if finish_resp.status_code == 200:
                video_id = finish_resp.json().get("video_id")
                logger.info("Resumable upload complete: video_id=%s", video_id)
                return video_id
            logger.error("Resumable finish failed: %s", finish_resp.text[:200])
            return None
        except Exception as exc:
            logger.error("_resumable_upload error: %s", exc, exc_info=True)
            return None

    # ── Async upload (non-blocking) ───────────────────────────────────────────

    async def upload_video_async(
        self,
        video_path: str,
        title: str,
        description: str = "",
        schedule_time: Optional[datetime] = None,
        is_reels: bool = True,
    ) -> Optional[str]:
        """Async upload using httpx (for use in async FastAPI context)."""
        import asyncio

        return await asyncio.to_thread(
            self.upload_video, video_path, title, description, schedule_time, is_reels
        )

    # ── Insights ──────────────────────────────────────────────────────────────

    def get_video_insights(self, video_id: str) -> Optional[Dict[str, Any]]:
        if not video_id:
            return None
        try:
            r = requests.get(
                f"{self.graph}/{video_id}",
                params={
                    "fields": "description,created_time,status,length,picture,video_insights.limit(100){name,values}",
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            insights: Dict[str, Any] = {
                "video_id": video_id,
                "description": data.get("description"),
                "created_time": data.get("created_time"),
                "status": data.get("status"),
                "duration": data.get("length"),
            }
            for item in data.get("video_insights", {}).get("data", []):
                vals = item.get("values", [])
                if vals:
                    insights[item["name"]] = vals[0].get("value", 0)
            return insights
        except Exception as exc:
            logger.error("get_video_insights error: %s", exc)
            return None

    def get_reel_status(self, video_id: str) -> Optional[str]:
        """Poll the processing status of an uploaded reel."""
        try:
            r = requests.get(
                f"{self.graph}/{video_id}",
                params={"fields": "status", "access_token": self.access_token},
                timeout=15,
            )
            if r.status_code == 200:
                return r.json().get("status", {}).get("video_status")
        except Exception as exc:
            logger.warning("get_reel_status error: %s", exc)
        return None

    def get_page_insights(self) -> Optional[Dict[str, Any]]:
        try:
            r = requests.get(
                f"{self.graph}/{self.page_id}/insights",
                params={
                    "metric": "page_views_total,page_fans,page_engaged_users,page_video_views",
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            if r.status_code != 200:
                return None
            insights: Dict[str, Any] = {}
            for item in r.json().get("data", []):
                vals = item.get("values", [])
                if vals:
                    insights[item["name"]] = vals[0].get("value", 0)
            return insights
        except Exception as exc:
            logger.error("get_page_insights error: %s", exc)
            return None

    def create_post(
        self, video_id: str, caption: str = "", hashtags: Optional[list] = None
    ) -> Optional[str]:
        if hashtags:
            caption = caption + " " + " ".join(hashtags)
        try:
            r = requests.post(
                f"{self.graph}/{self.page_id}/feed",
                data={
                    "object_attachment": video_id,
                    "message": caption[:2000],
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            if r.status_code in (200, 201):
                return r.json().get("id")
        except Exception as exc:
            logger.error("create_post error: %s", exc)
        return None
