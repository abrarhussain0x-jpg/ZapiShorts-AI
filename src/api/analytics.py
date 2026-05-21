"""Analytics API — funnel, performance, storage, A/B reports with caching."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.database import get_db
from src.database.models import (FacebookUpload, ProcessedShort, SourceVideo,
                                 VideoStatusEnum)
from src.services.metadata_generator import MetadataGenerator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/dashboard", summary="High-level dashboard metrics")
async def get_dashboard(db: Session = Depends(get_db)):
    """Returns aggregated pipeline metrics. Safe for cold-starts (returns 0s)."""
    videos_q = db.query(
        func.count(SourceVideo.id).label("total"),
        func.sum(SourceVideo.duration_seconds).label("duration"),
    ).first()
    total_videos = videos_q.total if videos_q else 0
    total_duration = videos_q.duration or 0

    shorts_count = db.query(func.count(ProcessedShort.id)).scalar() or 0

    uploads_q = (
        db.query(
            func.count(FacebookUpload.id).label("total"),
            func.sum(FacebookUpload.views).label("views"),
            func.sum(FacebookUpload.likes).label("likes"),
        )
        .filter(FacebookUpload.status == VideoStatusEnum.UPLOADED)
        .first()
    )

    total_uploads = uploads_q.total if uploads_q else 0
    total_views = uploads_q.views or 0
    total_likes = uploads_q.likes or 0

    return {
        "status": "success",
        "pipeline": {
            "source_videos": total_videos,
            "processed_shorts": shorts_count,
            "successful_uploads": total_uploads,
            "total_source_hours": round(total_duration / 3600, 2),
        },
        "engagement": {
            "total_views": total_views,
            "total_likes": total_likes,
            "avg_views_per_video": round(total_views / max(total_uploads, 1), 1),
            "avg_engagement_rate": (
                round(total_likes / max(total_views, 1) * 100, 2)
                if total_views > 0
                else 0.0
            ),
        },
    }


@router.get("/funnel", summary="Pipeline conversion funnel")
async def get_funnel(
    days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)
):
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Sources added
    sources = db.query(SourceVideo).filter(SourceVideo.created_at >= cutoff).count()

    # Sources successfully downloaded
    downloaded = (
        db.query(SourceVideo)
        .filter(
            SourceVideo.created_at >= cutoff,
            SourceVideo.status.in_(
                [
                    VideoStatusEnum.DOWNLOADED,
                    VideoStatusEnum.PROCESSING,
                    VideoStatusEnum.PROCESSED,
                ]
            ),
        )
        .count()
    )

    # Shorts generated
    shorts = (
        db.query(ProcessedShort).filter(ProcessedShort.created_at >= cutoff).count()
    )

    # Uploads completed
    uploads = (
        db.query(FacebookUpload)
        .filter(
            FacebookUpload.created_at >= cutoff,
            FacebookUpload.status == VideoStatusEnum.UPLOADED,
        )
        .count()
    )

    return {
        "period_days": days,
        "funnel": {
            "sources_added": sources,
            "sources_downloaded": downloaded,
            "shorts_generated": shorts,
            "uploads_completed": uploads,
        },
        "conversion_rates": {
            "download_success_rate": round((downloaded / max(sources, 1)) * 100, 1),
            "shorts_per_source": round(shorts / max(downloaded, 1), 1),
            "upload_success_rate": round((uploads / max(shorts, 1)) * 100, 1),
        },
    }


@router.get("/ab-report", summary="A/B Testing Win-Rate Report")
async def get_ab_report():
    gen = MetadataGenerator()
    return {"status": "success", "report": gen.export_ab_report()}


@router.get("/storage", summary="Disk usage breakdown")
async def get_storage():
    from src.config.settings import settings
    from src.utils.file_manager import get_directory_info

    return {
        "status": "success",
        "directories": {
            "downloads": get_directory_info(settings.downloads_dir or ""),
            "output": get_directory_info(settings.output_dir or ""),
            "logs": get_directory_info(settings.logs_dir or ""),
            "temp": get_directory_info(settings.temp_dir or ""),
        },
    }


@router.get("/performance", summary="Recent upload performance")
async def get_performance(
    limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)
):
    recent = (
        db.query(FacebookUpload)
        .filter(FacebookUpload.status == VideoStatusEnum.UPLOADED)
        .order_by(FacebookUpload.uploaded_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "status": "success",
        "count": len(recent),
        "recent_uploads": [
            {
                "id": u.id,
                "title": u.title,
                "platform": u.platform,
                "views": u.views,
                "likes": u.likes,
                "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
                "engagement_rate": (
                    round(u.likes / max(u.views, 1) * 100, 2) if u.views else 0.0
                ),
            }
            for u in recent
        ],
    }
