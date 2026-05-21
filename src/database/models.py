"""Production-grade database models — SQLAlchemy 2.0-style with JSON columns,
composite indexes, server-side timestamps, and full relationship graph."""

import enum
import uuid

from sqlalchemy import (JSON, Boolean, Column, DateTime, Enum, Float,
                        ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


# ── Enumerations ──────────────────────────────────────────────────────────────


class VideoStatusEnum(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VALIDATING = "validating"
    PROCESSING = "processing"
    PROCESSED = "processed"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class JobStatusEnum(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY = "retry"


class WebhookStatusEnum(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


# ── Models ────────────────────────────────────────────────────────────────────


class SourceVideo(Base):
    """YouTube source video."""

    __tablename__ = "source_videos"
    __table_args__ = (
        Index("idx_sv_youtube_id", "youtube_id"),
        Index("idx_sv_status_created", "status", "created_at"),
        Index("idx_sv_channel_id", "channel_id"),
        UniqueConstraint("youtube_id", name="uq_sv_youtube_id"),
    )

    id = Column(
        String(50), primary_key=True, default=lambda: f"src_{uuid.uuid4().hex[:12]}"
    )
    youtube_id = Column(String(50), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    channel_id = Column(String(50), nullable=False, index=True)
    channel_name = Column(String(255))
    duration_seconds = Column(Integer)
    thumbnail_url = Column(String(500))
    published_at = Column(DateTime)
    downloaded_at = Column(DateTime)
    local_path = Column(String(500))
    thumbnail_path = Column(String(500))
    file_size_bytes = Column(Integer, default=0)
    status = Column(
        Enum(VideoStatusEnum),
        default=VideoStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    error_message = Column(Text)
    error_code = Column(String(50))
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    video_metadata = Column(JSON)  # replaces metadata_json text blob
    tags = Column(String(500))

    # Relationships
    processed_shorts = relationship(
        "ProcessedShort", back_populates="source_video", cascade="all, delete-orphan"
    )
    processing_jobs = relationship(
        "ProcessingJob", back_populates="source_video", cascade="all, delete-orphan"
    )

    # Server-side timestamps (DB stamps, not Python)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<SourceVideo {self.youtube_id} [{self.status}]>"


class ProcessedShort(Base):
    """Processed short-form video clip."""

    __tablename__ = "processed_shorts"
    __table_args__ = (
        Index("idx_ps_source_status", "source_video_id", "status"),
        Index("idx_ps_platform", "platform_profile"),
        Index("idx_ps_variant_group", "variant_group_id"),
        Index("idx_ps_created", "created_at"),
        UniqueConstraint("idempotency_key", name="uq_ps_idempotency_key"),
    )

    id = Column(
        String(50), primary_key=True, default=lambda: f"short_{uuid.uuid4().hex[:12]}"
    )
    source_video_id = Column(String(50), ForeignKey("source_videos.id"), nullable=False)
    output_path = Column(String(500), nullable=False)
    output_filename = Column(String(255))
    thumbnail_path = Column(String(500))
    duration_seconds = Column(Integer)
    file_size_bytes = Column(Integer, default=0)
    resolution = Column(String(20))
    fps = Column(Integer)
    bitrate = Column(String(20))
    has_captions = Column(Boolean, default=False)
    caption_language = Column(String(10), default="en")
    audio_track = Column(String(500))
    audio_loudness_lufs = Column(Float)
    processing_time_seconds = Column(Float, default=0.0)
    status = Column(
        Enum(VideoStatusEnum),
        default=VideoStatusEnum.PROCESSED,
        nullable=False,
        index=True,
    )
    quality_score = Column(Float, default=0.0)
    error_message = Column(Text)
    segment_start_seconds = Column(Float, default=0.0)
    segment_end_seconds = Column(Float)
    segment_number = Column(Integer, default=1)
    effects_applied = Column(String(500))
    platform_profile = Column(String(64), default="facebook_reels", index=True)
    variant_group_id = Column(String(64), index=True)
    idempotency_key = Column(String(128), unique=True, nullable=True)
    watermark_applied = Column(Boolean, default=False)
    clip_score_data = Column(JSON)  # replaces clip_score_json text blob

    # Relationships
    source_video = relationship("SourceVideo", back_populates="processed_shorts")
    facebook_uploads = relationship(
        "FacebookUpload", back_populates="processed_short", cascade="all, delete-orphan"
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<ProcessedShort {self.id} [{self.status}]>"


class FacebookUpload(Base):
    """Upload record for Facebook / other platforms."""

    __tablename__ = "facebook_uploads"
    __table_args__ = (
        Index("idx_fu_short_status", "processed_short_id", "status"),
        Index("idx_fu_platform", "platform"),
        Index("idx_fu_variant_group", "variant_group_id"),
        Index("idx_fu_uploaded_at", "uploaded_at"),
        UniqueConstraint("idempotency_key", name="uq_fu_idempotency_key"),
    )

    id = Column(
        String(50), primary_key=True, default=lambda: f"fbup_{uuid.uuid4().hex[:12]}"
    )
    processed_short_id = Column(
        String(50), ForeignKey("processed_shorts.id"), nullable=False
    )
    facebook_post_id = Column(String(100), unique=True, nullable=True)
    facebook_video_id = Column(String(100), unique=True, nullable=True)
    title = Column(String(255))
    description = Column(Text)
    status = Column(
        Enum(VideoStatusEnum),
        default=VideoStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    uploaded_at = Column(DateTime)
    scheduled_for = Column(DateTime)
    published_at = Column(DateTime)
    platform = Column(String(64), default="facebook_reels", index=True)
    variant_group_id = Column(String(64), index=True)
    variant_label = Column(String(16))
    cta_style = Column(String(32))
    idempotency_key = Column(String(128), unique=True, nullable=True)
    is_winner = Column(Boolean, default=False)

    # Engagement metrics
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    engagement_rate = Column(Float, default=0.0)
    reach = Column(Integer, default=0)
    impressions = Column(Integer, default=0)

    hashtags = Column(String(1000))
    mentions = Column(String(500))
    error_message = Column(Text)
    error_code = Column(String(50))
    api_response = Column(JSON)  # replaces api_response text blob

    # Relationships
    processed_short = relationship("ProcessedShort", back_populates="facebook_uploads")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime)

    def __repr__(self) -> str:
        return f"<FacebookUpload {self.facebook_video_id} [{self.status}]>"


class ProcessingJob(Base):
    """Tracks every pipeline job stage."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("idx_pj_source_status", "source_video_id", "status"),
        Index("idx_pj_type_status", "job_type", "status"),
        Index("idx_pj_created", "created_at"),
    )

    id = Column(
        String(50), primary_key=True, default=lambda: f"job_{uuid.uuid4().hex[:12]}"
    )
    source_video_id = Column(String(50), ForeignKey("source_videos.id"), nullable=False)
    job_type = Column(String(50), nullable=False)
    status = Column(
        Enum(JobStatusEnum), default=JobStatusEnum.PENDING, nullable=False, index=True
    )

    # Progress
    progress = Column(Float, default=0.0)
    total_steps = Column(Integer, default=100)
    current_step = Column(Integer, default=0)
    progress_message = Column(String(500))

    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    estimated_completion = Column(DateTime)
    duration_seconds = Column(Float, default=0.0)

    # Error handling
    error_message = Column(Text)
    error_code = Column(String(50))
    error_traceback = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime)

    job_metadata = Column(JSON)
    worker_id = Column(String(100))
    celery_task_id = Column(String(100))

    source_video = relationship("SourceVideo", back_populates="processing_jobs")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.id} [{self.job_type}/{self.status}]>"


class VideoChannel(Base):
    """Tracks YouTube channel sync state."""

    __tablename__ = "video_channels"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_vc_channel_id"),)

    id = Column(
        String(50), primary_key=True, default=lambda: f"ch_{uuid.uuid4().hex[:12]}"
    )
    channel_id = Column(String(100), unique=True, nullable=False)
    channel_url = Column(String(500))
    channel_name = Column(String(255))
    last_checked_at = Column(DateTime)
    next_check_at = Column(DateTime)
    total_videos_found = Column(Integer, default=0)
    total_videos_processed = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    check_interval_seconds = Column(Integer, default=3600)
    channel_metadata = Column(JSON)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<VideoChannel {self.channel_id}>"


class SystemMetrics(Base):
    """Time-series system and performance metrics."""

    __tablename__ = "system_metrics"
    __table_args__ = (Index("idx_sm_name_ts", "metric_name", "timestamp"),)

    id = Column(
        String(50), primary_key=True, default=lambda: f"metric_{uuid.uuid4().hex[:12]}"
    )
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    metric_unit = Column(String(50))
    tags = Column(JSON)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<SystemMetrics {self.metric_name}={self.metric_value}>"


class AuditLog(Base):
    """Immutable audit trail."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_al_action_ts", "action", "timestamp"),
        Index("idx_al_entity", "entity_type", "entity_id"),
    )

    id = Column(
        String(50), primary_key=True, default=lambda: f"audit_{uuid.uuid4().hex[:12]}"
    )
    action = Column(String(100), nullable=False)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(String(100))
    old_value = Column(JSON)
    new_value = Column(JSON)
    user_id = Column(String(100))
    ip_address = Column(String(50))
    request_id = Column(String(100))
    status = Column(String(50))
    error_message = Column(Text)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} on {self.entity_type}>"


class WebhookEvent(Base):
    """Outgoing webhook delivery records."""

    __tablename__ = "webhook_events"
    __table_args__ = (Index("idx_we_status_created", "status", "created_at"),)

    id = Column(
        String(50), primary_key=True, default=lambda: f"wh_{uuid.uuid4().hex[:12]}"
    )
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    target_url = Column(String(500), nullable=False)
    status = Column(
        Enum(WebhookStatusEnum),
        default=WebhookStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    http_status_code = Column(Integer)
    response_body = Column(Text)
    attempts = Column(Integer, default=0)
    last_attempt_at = Column(DateTime)
    next_retry_at = Column(DateTime)
    error_message = Column(Text)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<WebhookEvent {self.event_type} [{self.status}]>"
