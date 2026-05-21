"""Advanced endpoints — reprocess, audio norm, thumbnail generation."""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.core.processor import VideoProcessor
from src.database.database import get_db
from src.database.models import ProcessedShort, SourceVideo, VideoStatusEnum
from src.services.ab_testing import ABTestingEngine
from src.services.clip_scorer import AIClipScoringEngine
from src.services.metadata_generator import MetadataGenerator
from src.services.multi_platform import (PLATFORM_PROFILES,
                                         is_supported_platform,
                                         normalize_platform_name,
                                         resolve_profiles,
                                         validate_platform_names)
from src.services.video_editor import VideoEditor
from src.utils.validators import (FileValidator, NumberValidator,
                                  StringValidator, URLValidator)

logger = logging.getLogger(__name__)
router = APIRouter()


class ClipCandidate(BaseModel):
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)


class ClipScoreRequest(BaseModel):
    video_path: str
    context_text: str = ""
    candidates: List[ClipCandidate] = Field(default_factory=list)


class MetadataVariantRequest(BaseModel):
    source_title: str
    source_description: str = ""
    variant_count: int = Field(default=3, ge=2, le=4)
    platform: str = "facebook"


class ABWinnerRequest(BaseModel):
    variant_group_id: str


class ProcessWithPlatformsRequest(BaseModel):
    youtube_url: str
    platforms: Optional[List[str]] = None
    num_shorts: int = Field(default=3, ge=1, le=10)
    create_shorts: bool = True
    upload_to_facebook: bool = True


@router.get("/platforms", summary="List Platform Profiles")
async def list_platforms() -> Dict[str, Any]:
    return {
        "status": "success",
        "profiles": [
            {
                "name": p.name,
                "width": p.width,
                "height": p.height,
                "fps": p.fps,
                "bitrate": p.bitrate,
                "codec": p.codec,
                "format": p.format,
            }
            for p in resolve_profiles(None)
        ],
    }


@router.post("/process-with-platforms", summary="Process Video for Specific Platforms")
async def process_with_platforms(
    payload: ProcessWithPlatformsRequest, db: Session = Depends(get_db)
):
    if not URLValidator.is_youtube_url(payload.youtube_url):
        raise HTTPException(status_code=422, detail="Invalid YouTube URL")

    # Validate platforms before processing
    if payload.platforms:
        _, invalid = validate_platform_names(payload.platforms)
        if invalid:
            raise HTTPException(
                status_code=422, detail=f"Unsupported platforms: {invalid}"
            )

    processor = VideoProcessor()
    source_id = processor.process_youtube_url(
        youtube_url=payload.youtube_url,
        db=db,
        create_shorts=payload.create_shorts,
        upload_to_facebook=payload.upload_to_facebook,
        num_shorts=payload.num_shorts,
        platforms=payload.platforms,
    )
    if not source_id:
        raise HTTPException(status_code=500, detail="Processing failed")

    return {"status": "success", "source_id": source_id}


@router.post("/clip-score", summary="Score Candidate Clips")
async def score_clips(payload: ClipScoreRequest) -> Dict[str, Any]:
    FileValidator.validate_video_path(payload.video_path)
    scorer = AIClipScoringEngine()
    candidates = [(c.start, c.end) for c in payload.candidates]
    ranked = scorer.rank_segments(
        payload.video_path, candidates, context_text=payload.context_text
    )

    return {
        "status": "success",
        "count": len(ranked),
        "scores": [scorer.explain_score(s) for s in ranked],
    }


@router.post("/metadata/variants", summary="Generate Metadata Variants")
async def generate_metadata_variants(payload: MetadataVariantRequest) -> Dict[str, Any]:
    StringValidator.validate_title(payload.source_title)
    StringValidator.validate_description(payload.source_description)
    NumberValidator.validate_positive_integer(payload.variant_count, "variant_count")

    platform = normalize_platform_name(payload.platform)
    if not is_supported_platform(platform):
        raise HTTPException(
            status_code=422, detail=f"Unsupported platform: {payload.platform}"
        )

    gen = MetadataGenerator()
    variants = gen.generate_variants(
        source_title=payload.source_title,
        source_description=payload.source_description,
        variant_count=payload.variant_count,
        platform=platform,
    )

    return {
        "status": "success",
        "platform": platform,
        "variants": [
            {
                "label": v.variant_label,
                "style": v.cta_style,
                "hook": v.hook_line,
                "title": v.title,
                "caption": v.caption,
                "hashtags": v.hashtags,
            }
            for v in variants
        ],
    }


@router.post("/ab/pick-winner", summary="Pick A/B Winner")
async def pick_ab_winner(
    payload: ABWinnerRequest, db: Session = Depends(get_db)
) -> Dict[str, Any]:
    engine = ABTestingEngine()
    winner = engine.pick_winner(db, payload.variant_group_id)
    if not winner:
        raise HTTPException(status_code=404, detail="No variants found")
    return {
        "status": "success",
        "winner": {
            "id": winner.id,
            "video_id": winner.facebook_video_id,
            "style": winner.cta_style,
            "is_winner": winner.is_winner,
        },
    }


@router.post(
    "/reprocess/{short_id}", summary="Reprocess an existing short to a new platform"
)
async def reprocess_short(
    short_id: str,
    platform: str = Query(..., description="e.g. tiktok, youtube_shorts"),
    db: Session = Depends(get_db),
):
    short = db.query(ProcessedShort).filter(ProcessedShort.id == short_id).first()
    if not short:
        raise HTTPException(status_code=404, detail="Short not found")

    src = db.query(SourceVideo).filter(SourceVideo.id == short.source_video_id).first()
    if not src or not os.path.exists(src.local_path):
        raise HTTPException(
            status_code=400, detail="Source video file no longer available"
        )

    norm_plat = normalize_platform_name(platform)
    if not is_supported_platform(norm_plat):
        raise HTTPException(status_code=422, detail=f"Unsupported platform: {platform}")

    profile = PLATFORM_PROFILES[norm_plat]
    new_id = f"short_{uuid.uuid4().hex[:12]}_{norm_plat}"
    out_path = os.path.join(settings.output_dir, f"{new_id}.{profile.format}")

    editor = VideoEditor()
    success = editor.create_short(
        src.local_path,
        out_path,
        start_time=short.segment_start_seconds,
        duration=short.duration_seconds,
        target_width=profile.width,
        target_height=profile.height,
        target_fps=profile.fps,
        target_bitrate=profile.bitrate,
        watermark_text=f"{profile.name.upper()} | ZAPI",
    )

    if not success:
        raise HTTPException(status_code=500, detail="Reprocessing failed")

    new_short = ProcessedShort(
        id=new_id,
        source_video_id=src.id,
        output_path=out_path,
        duration_seconds=short.duration_seconds,
        platform_profile=norm_plat,
        status=VideoStatusEnum.PROCESSED,
        variant_group_id=short.variant_group_id,
        segment_start_seconds=short.segment_start_seconds,
        segment_end_seconds=short.segment_end_seconds,
    )
    db.add(new_short)
    db.commit()

    return {"status": "success", "new_short_id": new_id, "platform": norm_plat}
