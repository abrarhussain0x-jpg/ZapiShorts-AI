"""Scheduling API endpoints for smart publishing and scheduled uploads."""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.database.database import get_db
from src.database.models import FacebookUpload, ProcessedShort, VideoStatusEnum
from src.services.facebook_uploader import FacebookUploader
from src.services.multi_platform import normalize_platform_name
from src.services.smart_scheduler import SmartScheduler

logger = logging.getLogger(__name__)
router = APIRouter()


class SchedulePreviewRequest(BaseModel):
    count: int = Field(default=3, ge=1, le=10)
    days_ahead: int = Field(default=7, ge=1, le=30)
    history_days: int = Field(default=30, ge=1, le=365)
    preferred_hours: Optional[List[int]] = None
    timezone_offset_minutes: int = Field(default=0, ge=-720, le=840)


class PublishScheduledShortRequest(BaseModel):
    processed_short_id: str
    schedule_time: Optional[datetime] = None
    platform: str = "facebook"
    title: Optional[str] = None
    description: Optional[str] = None
    hashtags: List[str] = Field(default_factory=list)


def _platform_is_supported_for_facebook(platform: str) -> bool:
    normalized = normalize_platform_name(platform)
    return normalized == "facebook_reels"


def _idempotency_key(
    processed_short_id: str, schedule_time: datetime, platform: str
) -> str:
    raw = (
        f"{processed_short_id}:{schedule_time.isoformat(timespec='seconds')}:{platform}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _append_hashtags(description: str, hashtags: List[str]) -> str:
    if not hashtags:
        return description
    suffix = " ".join(
        tag if tag.startswith("#") else f"#{tag.lstrip('#')}" for tag in hashtags
    )
    return f"{description} {suffix}".strip()


def build_schedule_preview(
    db: Session,
    count: int = 3,
    days_ahead: int = 7,
    history_days: int = 30,
    preferred_hours: Optional[List[int]] = None,
    timezone_offset_minutes: int = 0,
) -> Dict[str, Any]:
    """Build a schedule preview using the database history when available."""
    scheduler = SmartScheduler()
    history_uploads = []

    try:
        cutoff_date = datetime.utcnow() - timedelta(days=history_days)
        history_uploads = (
            db.query(FacebookUpload)
            .filter(
                FacebookUpload.uploaded_at != None,
                FacebookUpload.uploaded_at >= cutoff_date,
            )
            .all()
        )
    except OperationalError as exc:
        logger.warning(
            "Scheduling preview falling back to defaults until database is ready: %s",
            exc,
        )

    slots = scheduler.recommend_slots(
        count=count,
        days_ahead=days_ahead,
        preferred_hours=preferred_hours,
        history_uploads=history_uploads,
        timezone_offset_minutes=timezone_offset_minutes,
    )

    history_hours = (
        scheduler.infer_best_hours(history_uploads) if history_uploads else []
    )
    source = "historical" if history_hours else "default"

    return {
        "status": "success",
        "source": source,
        "count": len(slots),
        "history_samples": len(history_uploads),
        "best_hours": history_hours[:5],
        "recommended_slots": [
            {
                "publish_at": slot.publish_at.isoformat(timespec="seconds") + "Z",
                "hour": slot.hour,
                "score": round(slot.score, 3),
            }
            for slot in slots
        ],
    }


def execute_publish_scheduled_short(
    db: Session,
    processed_short_id: str,
    schedule_time: Optional[datetime] = None,
    platform: str = "facebook",
    title: Optional[str] = None,
    description: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Publish or schedule a processed short for Facebook."""
    hashtags = hashtags or []

    if not _platform_is_supported_for_facebook(platform):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "This publish endpoint only supports Facebook targets",
                "platform": platform,
            },
        )

    processed_short = (
        db.query(ProcessedShort).filter(ProcessedShort.id == processed_short_id).first()
    )
    if not processed_short:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Processed short not found"
        )

    if processed_short.status not in {
        VideoStatusEnum.PROCESSED,
        VideoStatusEnum.UPLOADED,
        VideoStatusEnum.PUBLISHED,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Processed short is not ready for publishing",
        )

    scheduler = SmartScheduler()
    if schedule_time is None:
        slots = scheduler.recommend_slots(count=1)
        schedule_time = (
            slots[0].publish_at if slots else datetime.utcnow() + timedelta(hours=2)
        )

    if schedule_time <= datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Schedule time must be in the future",
        )

    normalized_platform = normalize_platform_name(platform)
    idempotency_key = _idempotency_key(
        processed_short.id, schedule_time, normalized_platform
    )

    existing_upload = (
        db.query(FacebookUpload)
        .filter(FacebookUpload.idempotency_key == idempotency_key)
        .first()
    )
    if existing_upload:
        return {
            "status": "success",
            "upload_id": existing_upload.id,
            "facebook_video_id": existing_upload.facebook_video_id,
            "scheduled_for": (
                existing_upload.scheduled_for.isoformat(timespec="seconds") + "Z"
                if existing_upload.scheduled_for
                else None
            ),
            "idempotency_key": idempotency_key,
            "message": "Existing scheduled upload returned",
        }

    source_video = processed_short.source_video
    upload_title = (
        title
        or getattr(source_video, "title", None)
        or processed_short.output_filename
        or "ZAPI Short"
    )
    upload_description = _append_hashtags(
        description or getattr(source_video, "description", "") or "",
        hashtags,
    )

    uploader = FacebookUploader()
    video_id = uploader.upload_video(
        processed_short.output_path,
        upload_title,
        upload_description,
        schedule_time=schedule_time,
        is_reels=True,
    )

    upload = FacebookUpload(
        id=f"fbup_{idempotency_key[:12]}",
        processed_short_id=processed_short.id,
        facebook_video_id=video_id,
        title=upload_title,
        description=upload_description,
        status=VideoStatusEnum.UPLOADED if video_id else VideoStatusEnum.FAILED,
        uploaded_at=datetime.utcnow() if video_id else None,
        scheduled_for=schedule_time,
        platform=normalized_platform,
        variant_group_id=processed_short.variant_group_id,
        variant_label=None,
        cta_style=None,
        idempotency_key=idempotency_key,
        is_winner=False,
        hashtags=" ".join(hashtags) if hashtags else None,
        error_message=None if video_id else "Upload failed",
    )

    db.add(upload)
    db.commit()
    db.refresh(upload)

    return {
        "status": "success",
        "upload_id": upload.id,
        "facebook_video_id": upload.facebook_video_id,
        "scheduled_for": schedule_time.isoformat(timespec="seconds") + "Z",
        "platform": normalized_platform,
        "idempotency_key": idempotency_key,
        "message": (
            "Short scheduled for Facebook upload"
            if schedule_time > datetime.utcnow()
            else "Short uploaded immediately"
        ),
    }


@router.post("/preview")
async def preview_schedule(
    payload: SchedulePreviewRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Return the best upcoming publish slots using recent upload performance when available."""
    return build_schedule_preview(
        db=db,
        count=payload.count,
        days_ahead=payload.days_ahead,
        history_days=payload.history_days,
        preferred_hours=payload.preferred_hours,
        timezone_offset_minutes=payload.timezone_offset_minutes,
    )


@router.post("/publish")
async def publish_scheduled_short(
    payload: PublishScheduledShortRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Schedule or immediately upload a processed short to Facebook."""
    return execute_publish_scheduled_short(
        db=db,
        processed_short_id=payload.processed_short_id,
        schedule_time=payload.schedule_time,
        platform=payload.platform,
        title=payload.title,
        description=payload.description,
        hashtags=payload.hashtags,
    )
