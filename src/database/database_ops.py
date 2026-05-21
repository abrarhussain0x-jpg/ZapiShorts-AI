"""Enhanced database operations and query helpers"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.orm import Session

from ..utils.exceptions import DatabaseError, NotFoundError
from .models import (AuditLog, FacebookUpload, JobStatusEnum, ProcessedShort,
                     ProcessingJob, SourceVideo, SystemMetrics,
                     VideoStatusEnum)


class VideoRepository:
    """Repository for video operations"""

    @staticmethod
    def create_source_video(db: Session, **kwargs) -> SourceVideo:
        """Create a source video"""
        video = SourceVideo(**kwargs)
        db.add(video)
        db.commit()
        db.refresh(video)
        return video

    @staticmethod
    def get_video(db: Session, video_id: str) -> Optional[SourceVideo]:
        """Get video by ID"""
        return db.query(SourceVideo).filter(SourceVideo.id == video_id).first()

    @staticmethod
    def get_video_by_youtube_id(db: Session, youtube_id: str) -> Optional[SourceVideo]:
        """Get video by YouTube ID"""
        return (
            db.query(SourceVideo).filter(SourceVideo.youtube_id == youtube_id).first()
        )

    @staticmethod
    def get_videos_by_channel(
        db: Session, channel_id: str, limit: int = 100
    ) -> List[SourceVideo]:
        """Get videos by channel"""
        return (
            db.query(SourceVideo)
            .filter(SourceVideo.channel_id == channel_id)
            .order_by(desc(SourceVideo.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_videos_by_status(
        db: Session, status: VideoStatusEnum, limit: int = 100
    ) -> List[SourceVideo]:
        """Get videos by status"""
        return (
            db.query(SourceVideo)
            .filter(SourceVideo.status == status)
            .order_by(asc(SourceVideo.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_pending_videos(db: Session, limit: int = 50) -> List[SourceVideo]:
        """Get pending videos"""
        return VideoRepository.get_videos_by_status(db, VideoStatusEnum.PENDING, limit)

    @staticmethod
    def get_failed_videos(db: Session, limit: int = 50) -> List[SourceVideo]:
        """Get failed videos"""
        return VideoRepository.get_videos_by_status(db, VideoStatusEnum.FAILED, limit)

    @staticmethod
    def update_video_status(
        db: Session,
        video_id: str,
        status: VideoStatusEnum,
        error_message: Optional[str] = None,
    ) -> SourceVideo:
        """Update video status"""
        video = VideoRepository.get_video(db, video_id)
        if not video:
            raise NotFoundError(f"Video {video_id} not found")

        video.status = status
        if error_message:
            video.error_message = error_message
        video.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(video)
        return video

    @staticmethod
    def increment_retry_count(db: Session, video_id: str) -> SourceVideo:
        """Increment retry count"""
        video = VideoRepository.get_video(db, video_id)
        if not video:
            raise NotFoundError(f"Video {video_id} not found")

        video.retry_count += 1
        db.commit()
        db.refresh(video)
        return video

    @staticmethod
    def delete_video(db: Session, video_id: str, soft: bool = False) -> bool:
        """Delete video (soft or hard)"""
        video = VideoRepository.get_video(db, video_id)
        if not video:
            raise NotFoundError(f"Video {video_id} not found")

        if soft:
            video.status = VideoStatusEnum.ARCHIVED
            video.updated_at = datetime.utcnow()
            db.commit()
        else:
            db.delete(video)
            db.commit()

        return True

    @staticmethod
    def get_video_stats(db: Session) -> Dict[str, int]:
        """Get video statistics"""
        total = db.query(func.count(SourceVideo.id)).scalar()
        by_status = (
            db.query(SourceVideo.status, func.count(SourceVideo.id))
            .group_by(SourceVideo.status)
            .all()
        )

        return {
            "total": total or 0,
            "by_status": {str(status): count for status, count in by_status},
        }


class ShortRepository:
    """Repository for processed shorts"""

    @staticmethod
    def create_short(db: Session, **kwargs) -> ProcessedShort:
        """Create a processed short"""
        short = ProcessedShort(**kwargs)
        db.add(short)
        db.commit()
        db.refresh(short)
        return short

    @staticmethod
    def get_short(db: Session, short_id: str) -> Optional[ProcessedShort]:
        """Get short by ID"""
        return db.query(ProcessedShort).filter(ProcessedShort.id == short_id).first()

    @staticmethod
    def get_shorts_for_video(db: Session, source_video_id: str) -> List[ProcessedShort]:
        """Get all shorts for a video"""
        return (
            db.query(ProcessedShort)
            .filter(ProcessedShort.source_video_id == source_video_id)
            .order_by(asc(ProcessedShort.segment_number))
            .all()
        )

    @staticmethod
    def get_shorts_by_status(
        db: Session, status: VideoStatusEnum, limit: int = 100
    ) -> List[ProcessedShort]:
        """Get shorts by status"""
        return (
            db.query(ProcessedShort)
            .filter(ProcessedShort.status == status)
            .order_by(desc(ProcessedShort.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_top_shorts_by_quality(db: Session, limit: int = 10) -> List[ProcessedShort]:
        """Get top shorts by quality score"""
        return (
            db.query(ProcessedShort)
            .order_by(desc(ProcessedShort.quality_score))
            .limit(limit)
            .all()
        )

    @staticmethod
    def update_short_status(
        db: Session, short_id: str, status: VideoStatusEnum
    ) -> ProcessedShort:
        """Update short status"""
        short = ShortRepository.get_short(db, short_id)
        if not short:
            raise NotFoundError(f"Short {short_id} not found")

        short.status = status
        short.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(short)
        return short

    @staticmethod
    def delete_short(db: Session, short_id: str) -> bool:
        """Delete short"""
        short = ShortRepository.get_short(db, short_id)
        if not short:
            raise NotFoundError(f"Short {short_id} not found")

        db.delete(short)
        db.commit()
        return True


class FacebookRepository:
    """Repository for Facebook uploads"""

    @staticmethod
    def create_upload(db: Session, **kwargs) -> FacebookUpload:
        """Create Facebook upload record"""
        upload = FacebookUpload(**kwargs)
        db.add(upload)
        db.commit()
        db.refresh(upload)
        return upload

    @staticmethod
    def get_upload(db: Session, upload_id: str) -> Optional[FacebookUpload]:
        """Get upload by ID"""
        return db.query(FacebookUpload).filter(FacebookUpload.id == upload_id).first()

    @staticmethod
    def get_upload_by_post_id(db: Session, post_id: str) -> Optional[FacebookUpload]:
        """Get upload by Facebook post ID"""
        return (
            db.query(FacebookUpload)
            .filter(FacebookUpload.facebook_post_id == post_id)
            .first()
        )

    @staticmethod
    def get_uploads_by_status(
        db: Session, status: VideoStatusEnum, limit: int = 100
    ) -> List[FacebookUpload]:
        """Get uploads by status"""
        return (
            db.query(FacebookUpload)
            .filter(
                FacebookUpload.status == status, FacebookUpload.deleted_at.is_(None)
            )
            .order_by(desc(FacebookUpload.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_top_performing_uploads(
        db: Session, limit: int = 10
    ) -> List[FacebookUpload]:
        """Get top performing uploads"""
        return (
            db.query(FacebookUpload)
            .order_by(desc(FacebookUpload.engagement_rate))
            .limit(limit)
            .all()
        )

    @staticmethod
    def update_engagement_metrics(
        db: Session, upload_id: str, **metrics
    ) -> FacebookUpload:
        """Update engagement metrics"""
        upload = FacebookRepository.get_upload(db, upload_id)
        if not upload:
            raise NotFoundError(f"Upload {upload_id} not found")

        for key, value in metrics.items():
            if hasattr(upload, key):
                setattr(upload, key, value)

        upload.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(upload)
        return upload

    @staticmethod
    def soft_delete_upload(db: Session, upload_id: str) -> FacebookUpload:
        """Soft delete upload"""
        upload = FacebookRepository.get_upload(db, upload_id)
        if not upload:
            raise NotFoundError(f"Upload {upload_id} not found")

        upload.deleted_at = datetime.utcnow()
        db.commit()
        db.refresh(upload)
        return upload


class JobRepository:
    """Repository for processing jobs"""

    @staticmethod
    def create_job(db: Session, **kwargs) -> ProcessingJob:
        """Create processing job"""
        job = ProcessingJob(**kwargs)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def get_job(db: Session, job_id: str) -> Optional[ProcessingJob]:
        """Get job by ID"""
        return db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()

    @staticmethod
    def get_jobs_for_video(db: Session, source_video_id: str) -> List[ProcessingJob]:
        """Get all jobs for a video"""
        return (
            db.query(ProcessingJob)
            .filter(ProcessingJob.source_video_id == source_video_id)
            .order_by(desc(ProcessingJob.created_at))
            .all()
        )

    @staticmethod
    def get_jobs_by_status(
        db: Session, status: JobStatusEnum, limit: int = 100
    ) -> List[ProcessingJob]:
        """Get jobs by status"""
        return (
            db.query(ProcessingJob)
            .filter(ProcessingJob.status == status)
            .order_by(asc(ProcessingJob.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_pending_jobs(db: Session, limit: int = 50) -> List[ProcessingJob]:
        """Get pending jobs"""
        return JobRepository.get_jobs_by_status(db, JobStatusEnum.PENDING, limit)

    @staticmethod
    def get_failed_jobs(db: Session, limit: int = 50) -> List[ProcessingJob]:
        """Get failed jobs"""
        return JobRepository.get_jobs_by_status(db, JobStatusEnum.FAILED, limit)

    @staticmethod
    def update_job_status(
        db: Session, job_id: str, status: JobStatusEnum, **updates
    ) -> ProcessingJob:
        """Update job status"""
        job = JobRepository.get_job(db, job_id)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")

        job.status = status
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)

        if status == JobStatusEnum.COMPLETED:
            job.completed_at = datetime.utcnow()
            job.duration_seconds = (job.completed_at - job.started_at).total_seconds()

        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def update_job_progress(
        db: Session,
        job_id: str,
        current_step: int,
        total_steps: int,
        message: Optional[str] = None,
    ) -> ProcessingJob:
        """Update job progress"""
        job = JobRepository.get_job(db, job_id)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")

        job.current_step = current_step
        job.total_steps = total_steps
        job.progress = (current_step / total_steps * 100) if total_steps > 0 else 0
        if message:
            job.progress_message = message

        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def increment_retry_count(db: Session, job_id: str) -> ProcessingJob:
        """Increment retry count"""
        job = JobRepository.get_job(db, job_id)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")

        job.retry_count += 1
        if job.retry_count >= job.max_retries:
            job.status = JobStatusEnum.FAILED

        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return job


class MetricsRepository:
    """Repository for system metrics"""

    @staticmethod
    def record_metric(
        db: Session, metric_name: str, value: float, unit: str = ""
    ) -> SystemMetrics:
        """Record a system metric"""
        metric = SystemMetrics(
            metric_name=metric_name, metric_value=value, metric_unit=unit
        )
        db.add(metric)
        db.commit()
        db.refresh(metric)
        return metric

    @staticmethod
    def get_metrics(
        db: Session, metric_name: str, hours: int = 24, limit: int = 1000
    ) -> List[SystemMetrics]:
        """Get metrics for a time period"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        return (
            db.query(SystemMetrics)
            .filter(
                SystemMetrics.metric_name == metric_name,
                SystemMetrics.timestamp >= cutoff_time,
            )
            .order_by(desc(SystemMetrics.timestamp))
            .limit(limit)
            .all()
        )


class AuditRepository:
    """Repository for audit logs"""

    @staticmethod
    def log_action(db: Session, action: str, entity_type: str, **kwargs) -> AuditLog:
        """Log an action"""
        log = AuditLog(action=action, entity_type=entity_type, **kwargs)
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    @staticmethod
    def get_logs(
        db: Session, entity_type: Optional[str] = None, limit: int = 100
    ) -> List[AuditLog]:
        """Get audit logs"""
        query = db.query(AuditLog)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)

        return query.order_by(desc(AuditLog.timestamp)).limit(limit).all()
