"""Celery tasks for Facebook uploading and polling."""

import logging
from datetime import datetime
from typing import Optional

from src.database.database import db_session
from src.database.models import FacebookUpload, VideoStatusEnum
from src.job_queue.job_queue import celery_app
from src.services.facebook_uploader import FacebookUploader

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def upload_to_facebook_task(
    self,
    processed_short_id: str,
    title: str,
    description: str,
    schedule_time: Optional[datetime] = None,
) -> Optional[str]:
    """Async wrapper for the standard Facebook upload."""
    logger.info("Starting upload_to_facebook_task for short %s", processed_short_id)
    with db_session() as db:
        from src.database.models import ProcessedShort

        short = (
            db.query(ProcessedShort)
            .filter(ProcessedShort.id == processed_short_id)
            .first()
        )
        if not short:
            logger.error("Short %s not found", processed_short_id)
            return None

        # Idempotency check if we already have an upload record
        existing = (
            db.query(FacebookUpload)
            .filter(
                FacebookUpload.processed_short_id == processed_short_id,
                FacebookUpload.status == VideoStatusEnum.UPLOADED,
            )
            .first()
        )
        if existing:
            return existing.facebook_video_id

        uploader = FacebookUploader()
        if not uploader.validate_token():
            logger.error("Facebook token invalid")
            raise self.retry(exc=Exception("Invalid token"), countdown=300)

        video_id = uploader.upload_video(
            video_path=short.output_path,
            title=title,
            description=description,
            schedule_time=schedule_time,
            is_reels=True,
        )

        if not video_id:
            raise self.retry(exc=Exception("Upload failed"), countdown=120)

        return video_id


@celery_app.task(bind=True, max_retries=5)
def poll_facebook_status_task(self, upload_id: str) -> str:
    """Poll the graph API until the video processing is complete."""
    with db_session() as db:
        upload = db.query(FacebookUpload).filter(FacebookUpload.id == upload_id).first()
        if not upload or not upload.facebook_video_id:
            return "not_found"

        uploader = FacebookUploader()
        status = uploader.get_reel_status(upload.facebook_video_id)

        if status == "ready":
            upload.status = VideoStatusEnum.PUBLISHED
            db.commit()
            return "published"
        elif status == "error":
            upload.status = VideoStatusEnum.FAILED
            upload.error_message = "Facebook processing failed"
            db.commit()
            return "failed"

        # Still processing
        logger.info("Reel %s still processing: %s", upload.facebook_video_id, status)
        raise self.retry(countdown=120)  # Check again in 2 minutes
