"""Celery tasks for YouTube channel sync and downloads."""

import logging
from typing import List, Optional

from src.database.database import db_session
from src.database.models import (JobStatusEnum, ProcessingJob, SourceVideo,
                                 VideoChannel)
from src.job_queue.job_queue import celery_app
from src.services.youtube_downloader import YouTubeDownloader

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def sync_channel_task(
    self, channel_id: str, max_videos: Optional[int] = 10
) -> List[str]:
    """Sync a YouTube channel, fetching its latest videos."""
    logger.info("Starting sync_channel_task for %s", channel_id)
    with db_session() as db:
        channel = (
            db.query(VideoChannel).filter(VideoChannel.channel_id == channel_id).first()
        )
        if not channel:
            logger.error("Channel %s not found in DB", channel_id)
            return []

        dl = YouTubeDownloader()
        try:
            urls = list(dl.iter_channel_video_urls(channel.channel_url, max_videos))
            channel.total_videos_found = len(urls)
            db.commit()

            from src.tasks.processing_tasks import process_video_task

            dispatched = []
            for url in urls:
                # Basic idempotency check
                vid_id = url.split("v=")[-1]
                if (
                    not db.query(SourceVideo)
                    .filter(SourceVideo.youtube_id == vid_id)
                    .first()
                ):
                    process_video_task.delay(
                        url, create_shorts=True, upload_to_facebook=False
                    )
                    dispatched.append(url)

            logger.info(
                "Dispatched %d new videos for channel %s", len(dispatched), channel_id
            )
            return dispatched
        except Exception as exc:
            logger.error("Channel sync failed: %s", exc)
            raise self.retry(exc=exc, countdown=60)
