"""Videos API — background task dispatch, full CRUD, batch, filter, pagination."""

import logging
import uuid
from typing import List, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException, Query,
                     status)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.database.database import db_session, get_db
from src.database.models import ProcessedShort, SourceVideo, VideoStatusEnum
from src.utils.validators import URLValidator

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Pydantic schemas ──────────────────────────────────────────────────────────


class SourceVideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    youtube_id: str
    title: str
    channel_id: str
    channel_name: Optional[str]
    duration_seconds: Optional[int]
    thumbnail_url: Optional[str]
    thumbnail_path: Optional[str]
    file_size_bytes: Optional[int]
    status: str
    error_message: Optional[str]
    retry_count: Optional[int]
    created_at: Optional[str]
    updated_at: Optional[str]

    @classmethod
    def from_orm_safe(cls, obj: SourceVideo) -> "SourceVideoResponse":
        return cls(
            id=obj.id,
            youtube_id=obj.youtube_id,
            title=obj.title,
            channel_id=obj.channel_id,
            channel_name=obj.channel_name,
            duration_seconds=obj.duration_seconds,
            thumbnail_url=obj.thumbnail_url,
            thumbnail_path=obj.thumbnail_path,
            file_size_bytes=obj.file_size_bytes,
            status=str(
                obj.status.value if hasattr(obj.status, "value") else obj.status
            ),
            error_message=obj.error_message,
            retry_count=obj.retry_count,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
            updated_at=obj.updated_at.isoformat() if obj.updated_at else None,
        )


class ProcessedShortResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_video_id: str
    output_path: str
    output_filename: Optional[str]
    thumbnail_path: Optional[str]
    duration_seconds: Optional[int]
    resolution: Optional[str]
    fps: Optional[int]
    file_size_bytes: Optional[int]
    has_captions: bool
    platform_profile: Optional[str]
    status: str
    quality_score: Optional[float]
    processing_time_seconds: Optional[float]
    segment_start_seconds: Optional[float]
    segment_end_seconds: Optional[float]
    segment_number: Optional[int]
    created_at: Optional[str]

    @classmethod
    def from_orm_safe(cls, obj: ProcessedShort) -> "ProcessedShortResponse":
        return cls(
            id=obj.id,
            source_video_id=obj.source_video_id,
            output_path=obj.output_path,
            output_filename=obj.output_filename,
            thumbnail_path=obj.thumbnail_path,
            duration_seconds=obj.duration_seconds,
            resolution=obj.resolution,
            fps=obj.fps,
            file_size_bytes=obj.file_size_bytes,
            has_captions=bool(obj.has_captions),
            platform_profile=obj.platform_profile,
            status=str(
                obj.status.value if hasattr(obj.status, "value") else obj.status
            ),
            quality_score=obj.quality_score,
            processing_time_seconds=obj.processing_time_seconds,
            segment_start_seconds=obj.segment_start_seconds,
            segment_end_seconds=obj.segment_end_seconds,
            segment_number=obj.segment_number,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
        )


class ProcessVideoRequest(BaseModel):
    youtube_url: str
    create_shorts: bool = True
    upload_to_facebook: bool = True
    num_shorts: int = Field(default=3, ge=1, le=10)
    platforms: Optional[List[str]] = None


class BatchProcessRequest(BaseModel):
    youtube_urls: List[str] = Field(..., min_length=1, max_length=20)
    create_shorts: bool = True
    upload_to_facebook: bool = False
    num_shorts: int = Field(default=2, ge=1, le=5)
    platforms: Optional[List[str]] = None


# ── Background task runner ────────────────────────────────────────────────────


def _run_process(youtube_url: str, job_id: str, **kwargs):
    """Execute the pipeline in a background task with its own DB session."""
    try:
        from src.api.websocket import ws_manager
        from src.core.processor import VideoProcessor

        with db_session() as db:
            broadcast = ws_manager.get_broadcast_fn(job_id)
            processor = VideoProcessor()
            processor.process_youtube_url(
                youtube_url, db, broadcast=broadcast, **kwargs
            )
    except Exception as exc:
        logger.error(
            "Background processing failed for %s: %s", youtube_url, exc, exc_info=True
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/process", status_code=202, summary="Submit a YouTube URL for processing")
async def process_video(
    request: ProcessVideoRequest, background_tasks: BackgroundTasks
):
    """Returns immediately with a job_id. Connect to /ws/jobs/{job_id} for live progress."""
    if not URLValidator.is_youtube_url(request.youtube_url):
        raise HTTPException(status_code=422, detail="Invalid YouTube URL")

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    background_tasks.add_task(
        _run_process,
        request.youtube_url,
        job_id,
        create_shorts=request.create_shorts,
        upload_to_facebook=request.upload_to_facebook,
        num_shorts=request.num_shorts,
        platforms=request.platforms,
    )
    logger.info("Dispatched background job %s for %s", job_id, request.youtube_url)
    return {
        "status": "accepted",
        "job_id": job_id,
        "websocket_url": f"/ws/jobs/{job_id}",
        "message": "Processing started in background. Monitor progress via WebSocket.",
    }


@router.post("/batch", status_code=202, summary="Submit multiple YouTube URLs")
async def batch_process(
    request: BatchProcessRequest, background_tasks: BackgroundTasks
):
    """Dispatch a background task for each URL. Returns list of job IDs."""
    invalid = [u for u in request.youtube_urls if not URLValidator.is_youtube_url(u)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid URLs: {invalid}")

    jobs = []
    for url in request.youtube_urls:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        background_tasks.add_task(
            _run_process,
            url,
            job_id,
            create_shorts=request.create_shorts,
            upload_to_facebook=request.upload_to_facebook,
            num_shorts=request.num_shorts,
            platforms=request.platforms,
        )
        jobs.append(
            {
                "youtube_url": url,
                "job_id": job_id,
                "websocket_url": f"/ws/jobs/{job_id}",
            }
        )

    return {"status": "accepted", "count": len(jobs), "jobs": jobs}


@router.get("/videos", summary="List source videos with filtering and pagination")
async def list_videos(
    status: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(SourceVideo)
    if status:
        try:
            q = q.filter(SourceVideo.status == VideoStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
    if channel_id:
        q = q.filter(SourceVideo.channel_id == channel_id)

    q = q.order_by(SourceVideo.created_at.desc())
    total = q.count()
    videos = q.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "videos": [SourceVideoResponse.from_orm_safe(v) for v in videos],
    }


@router.get("/videos/{video_id}", summary="Get a single source video with its shorts")
async def get_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(SourceVideo).filter(SourceVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    shorts = (
        db.query(ProcessedShort)
        .filter(ProcessedShort.source_video_id == video_id)
        .all()
    )
    return {
        "video": SourceVideoResponse.from_orm_safe(video),
        "shorts": [ProcessedShortResponse.from_orm_safe(s) for s in shorts],
        "shorts_count": len(shorts),
    }


@router.delete("/videos/{video_id}", summary="Soft-delete a source video")
async def delete_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(SourceVideo).filter(SourceVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video.status = VideoStatusEnum.ARCHIVED
    db.commit()
    return {"status": "archived", "video_id": video_id}


@router.get("/shorts", summary="List all processed shorts")
async def list_shorts(
    platform: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(ProcessedShort)
    if platform:
        q = q.filter(ProcessedShort.platform_profile == platform)
    if status:
        try:
            q = q.filter(ProcessedShort.status == VideoStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
    q = q.order_by(ProcessedShort.created_at.desc())
    total = q.count()
    shorts = q.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "shorts": [ProcessedShortResponse.from_orm_safe(s) for s in shorts],
    }


@router.get("/shorts/{short_id}", summary="Get a specific short")
async def get_short(short_id: str, db: Session = Depends(get_db)):
    short = db.query(ProcessedShort).filter(ProcessedShort.id == short_id).first()
    if not short:
        raise HTTPException(status_code=404, detail="Short not found")
    source = (
        db.query(SourceVideo).filter(SourceVideo.id == short.source_video_id).first()
    )
    return {
        "short": ProcessedShortResponse.from_orm_safe(short),
        "source_video": SourceVideoResponse.from_orm_safe(source) if source else None,
    }


@router.post("/retry/{video_id}", summary="Retry failed video processing")
async def retry_processing(
    video_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    video = db.query(SourceVideo).filter(SourceVideo.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video.local_path:
        raise HTTPException(
            status_code=400, detail="No local file — re-submit the original URL"
        )

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    def _retry_shorts():
        from src.api.websocket import ws_manager
        from src.core.processor import VideoProcessor

        with db_session() as sess:
            src = sess.query(SourceVideo).filter(SourceVideo.id == video_id).first()
            if not src:
                return
            processor = VideoProcessor()
            processor._create_and_upload_shorts(
                source_video=src,
                db=sess,
                upload_to_facebook=True,
                num_shorts=3,
                platforms=["facebook_reels"],
                broadcast=ws_manager.get_broadcast_fn(job_id),
            )

    background_tasks.add_task(_retry_shorts)
    return {
        "status": "accepted",
        "job_id": job_id,
        "websocket_url": f"/ws/jobs/{job_id}",
    }
