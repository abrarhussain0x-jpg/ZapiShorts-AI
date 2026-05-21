"""Jobs API — list, detail, cancel, purge, logs."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.database.database import get_db
from src.database.models import JobStatusEnum, ProcessingJob, SourceVideo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", summary="List processing jobs")
async def list_jobs(
    status: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    source_video_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(ProcessingJob)
    if status:
        try:
            q = q.filter(ProcessingJob.status == JobStatusEnum(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status: {status}")
    if job_type:
        q = q.filter(ProcessingJob.job_type == job_type)
    if source_video_id:
        q = q.filter(ProcessingJob.source_video_id == source_video_id)

    q = q.order_by(ProcessingJob.created_at.desc())
    total = q.count()
    jobs = q.offset((page - 1) * size).limit(size).all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "jobs": [_serialize_job(j) for j in jobs],
    }


@router.get("/{job_id}", summary="Get a specific job")
async def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job)


@router.post("/{job_id}/cancel", summary="Cancel a running job")
async def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (
        JobStatusEnum.COMPLETED,
        JobStatusEnum.FAILED,
        JobStatusEnum.CANCELLED,
    ):
        raise HTTPException(
            status_code=400, detail=f"Job already in terminal state: {job.status.value}"
        )
    job.status = JobStatusEnum.CANCELLED
    db.commit()
    return {"status": "cancelled", "job_id": job_id}


@router.post("/purge-failed", summary="Delete all failed jobs")
async def purge_failed_jobs(db: Session = Depends(get_db)):
    count = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status == JobStatusEnum.FAILED)
        .delete()
    )
    db.commit()
    return {"status": "success", "deleted": count}


@router.get("/stats/summary", summary="Job statistics summary")
async def jobs_summary(db: Session = Depends(get_db)):
    from sqlalchemy import func

    rows = (
        db.query(ProcessingJob.status, func.count(ProcessingJob.id).label("count"))
        .group_by(ProcessingJob.status)
        .all()
    )
    avg_duration = (
        db.query(func.avg(ProcessingJob.duration_seconds))
        .filter(ProcessingJob.status == JobStatusEnum.COMPLETED)
        .scalar()
        or 0.0
    )
    return {
        "by_status": {str(r.status.value): r.count for r in rows},
        "avg_duration_seconds": round(float(avg_duration), 2),
    }


def _serialize_job(job: ProcessingJob) -> dict:
    return {
        "id": job.id,
        "source_video_id": job.source_video_id,
        "job_type": job.job_type,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "progress": job.progress,
        "progress_message": job.progress_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "duration_seconds": job.duration_seconds,
        "error_message": job.error_message,
        "retry_count": job.retry_count,
        "celery_task_id": job.celery_task_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
