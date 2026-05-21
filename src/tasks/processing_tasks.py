"""Celery tasks for the core video processing pipeline."""

import logging
import uuid
from typing import List, Optional

from src.database.database import db_session
from src.database.models import JobStatusEnum, ProcessingJob
from src.job_queue.job_queue import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def process_video_task(
    self,
    youtube_url: str,
    create_shorts: bool = True,
    upload_to_facebook: bool = True,
    num_shorts: int = 3,
    platforms: Optional[List[str]] = None,
) -> Optional[str]:
    """Execute the full pipeline asynchronously via Celery."""
    task_id = self.request.id or f"inline_{uuid.uuid4().hex[:8]}"
    logger.info("Starting process_video_task [%s] for %s", task_id, youtube_url)

    from src.api.websocket import ws_manager
    from src.core.processor import VideoProcessor

    job_id = None
    with db_session() as db:
        # Create a tracker record immediately so the API can find it by celery_task_id
        job = ProcessingJob(
            id=f"job_{uuid.uuid4().hex[:12]}",
            source_video_id="pending",  # updated inside process_youtube_url once fetched
            job_type="celery_pipeline",
            status=JobStatusEnum.RUNNING,
            celery_task_id=task_id,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    try:

        def _broadcast(data: dict):
            # Also update task meta for Celery result backend
            self.update_state(state="PROGRESS", meta=data)
            # Send to websocket
            ws_manager.get_broadcast_fn(job_id)(data)

        with db_session() as db:
            processor = VideoProcessor()
            source_id = processor.process_youtube_url(
                youtube_url=youtube_url,
                db=db,
                create_shorts=create_shorts,
                upload_to_facebook=upload_to_facebook,
                num_shorts=num_shorts,
                platforms=platforms,
                broadcast=_broadcast,
            )

            # Link job to actual video if successful
            if source_id:
                job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
                if job:
                    job.source_video_id = source_id
                    job.status = JobStatusEnum.COMPLETED
                    db.commit()

            return source_id

    except Exception as exc:
        logger.error("process_video_task failed: %s", exc, exc_info=True)
        with db_session() as db:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
            if job:
                job.status = JobStatusEnum.FAILED
                job.error_message = str(exc)
                db.commit()
        raise self.retry(exc=exc, countdown=120)
