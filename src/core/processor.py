"""Core video processor — orchestrates full pipeline with per-stage DB job tracking,
WebSocket progress broadcast, and async background task support."""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from src.config.settings import settings
from src.database.models import (FacebookUpload, JobStatusEnum, ProcessedShort,
                                 ProcessingJob, SourceVideo, VideoStatusEnum)
from src.services.caption_generator import CaptionGenerator
from src.services.facebook_uploader import FacebookUploader
from src.services.metadata_generator import MetadataGenerator
from src.services.multi_platform import (resolve_profiles,
                                         validate_platform_names)
from src.services.video_editor import VideoEditor
from src.services.youtube_downloader import YouTubeDownloader
from src.utils.validators import URLValidator

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Orchestrate the complete YouTube → Shorts → Facebook pipeline."""

    def __init__(self):
        self.downloader = YouTubeDownloader()
        self.editor = VideoEditor()
        self.caption_gen = CaptionGenerator()
        self.uploader = FacebookUploader()
        self.meta_gen = MetadataGenerator()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _idempotency_key(
        self, youtube_id: str, start: float, end: float, platform: str
    ) -> str:
        import uuid as _uuid

        raw = f"{youtube_id}:{start:.3f}:{end:.3f}:{platform}"
        return _uuid.uuid5(_uuid.NAMESPACE_URL, raw).hex

    def _variant_group_id(self, source_video: SourceVideo) -> str:
        return f"vg_{source_video.youtube_id}"

    # ── Job tracking helpers ──────────────────────────────────────────────────

    def _create_job(
        self, db: Session, source_video_id: str, job_type: str
    ) -> ProcessingJob:
        job = ProcessingJob(
            id=f"job_{uuid.uuid4().hex[:12]}",
            source_video_id=source_video_id,
            job_type=job_type,
            status=JobStatusEnum.RUNNING,
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def _update_job(
        self,
        db: Session,
        job: ProcessingJob,
        progress: float,
        message: str,
        status: Optional[JobStatusEnum] = None,
        error: Optional[str] = None,
        broadcast: Optional[Callable] = None,
    ) -> None:
        job.progress = progress
        job.progress_message = message
        if status:
            job.status = status
        if error:
            job.error_message = error
        if status in (JobStatusEnum.COMPLETED, JobStatusEnum.FAILED):
            job.completed_at = datetime.utcnow()
            if job.started_at:
                job.duration_seconds = (
                    job.completed_at - job.started_at
                ).total_seconds()
        db.commit()
        if broadcast:
            try:
                broadcast(
                    {"progress": progress, "stage": job.job_type, "message": message}
                )
            except Exception:
                pass

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def process_youtube_url(
        self,
        youtube_url: str,
        db: Session,
        create_shorts: bool = True,
        upload_to_facebook: bool = True,
        num_shorts: int = 3,
        platforms: Optional[List[str]] = None,
        broadcast: Optional[Callable] = None,
    ) -> Optional[str]:
        """Full synchronous pipeline — suitable for background task execution."""
        try:
            if not URLValidator.is_youtube_url(youtube_url):
                logger.error("Invalid YouTube URL: %s", youtube_url)
                return None

            num_shorts = max(1, min(num_shorts, settings.max_shorts_per_video))
            norm_platforms, invalid = validate_platform_names(platforms)
            if invalid:
                logger.error("Unsupported platforms: %s", invalid)
                return None
            resolved_names = [p.name for p in resolve_profiles(norm_platforms)]

            # ── Step 1: Fetch video info ────────────────────────────────────
            if broadcast:
                broadcast(
                    {"progress": 5, "stage": "info", "message": "Fetching video info…"}
                )
            video_info = self.downloader.get_video_info(youtube_url)
            if not video_info:
                logger.error("Could not fetch video info for %s", youtube_url)
                return None

            youtube_id = video_info["youtube_id"]

            # ── Idempotency check ──────────────────────────────────────────
            existing = (
                db.query(SourceVideo)
                .filter(SourceVideo.youtube_id == youtube_id)
                .first()
            )
            if existing:
                logger.info("Video already exists: %s", youtube_id)
                if existing.status in {
                    VideoStatusEnum.FAILED,
                    VideoStatusEnum.CANCELLED,
                }:
                    existing.status = (
                        VideoStatusEnum.DOWNLOADED
                        if existing.local_path
                        else VideoStatusEnum.PENDING
                    )
                    db.commit()
                return existing.id

            # Make a copy of video_info that is JSON serializable
            safe_video_info = dict(video_info)
            if isinstance(safe_video_info.get("published_at"), datetime):
                safe_video_info["published_at"] = safe_video_info[
                    "published_at"
                ].isoformat()

            # ── Create DB record ───────────────────────────────────────────
            source_video = SourceVideo(
                id=f"src_{uuid.uuid4().hex[:12]}",
                youtube_id=youtube_id,
                title=video_info["title"],
                description=video_info.get("description", ""),
                channel_id=video_info.get("channel_id", ""),
                channel_name=video_info.get("channel_name", ""),
                duration_seconds=video_info.get("duration_seconds", 0),
                thumbnail_url=video_info.get("thumbnail_url", ""),
                published_at=video_info.get("published_at"),
                status=VideoStatusEnum.DOWNLOADING,
                retry_count=0,
                max_retries=settings.job_retry_max_attempts,
                video_metadata=safe_video_info,
                tags=video_info.get("tags", ""),
            )
            db.add(source_video)
            db.commit()
            db.refresh(source_video)

            job = self._create_job(db, source_video.id, "download")

            # ── Step 2: Download ────────────────────────────────────────────
            if broadcast:
                broadcast(
                    {
                        "progress": 10,
                        "stage": "download",
                        "message": "Downloading video…",
                    }
                )
            download_result = self.downloader.download_video(youtube_url)
            if not download_result:
                source_video.status = VideoStatusEnum.FAILED
                source_video.error_message = "Download failed"
                self._update_job(db, job, 0, "Download failed", JobStatusEnum.FAILED)
                db.commit()
                return source_video.id

            source_video.local_path = download_result["local_path"]
            source_video.file_size_bytes = download_result.get("file_size_bytes", 0)
            source_video.status = VideoStatusEnum.DOWNLOADED
            source_video.downloaded_at = datetime.utcnow()
            self._update_job(db, job, 100, "Downloaded", JobStatusEnum.COMPLETED)
            db.commit()

            if not create_shorts:
                source_video.status = VideoStatusEnum.PROCESSED
                db.commit()
                return source_video.id

            # ── Step 3: Process shorts ──────────────────────────────────────
            source_video.status = VideoStatusEnum.PROCESSING
            db.commit()
            process_job = self._create_job(db, source_video.id, "process")

            if broadcast:
                broadcast(
                    {
                        "progress": 25,
                        "stage": "process",
                        "message": "Extracting best segments…",
                    }
                )

            self._create_and_upload_shorts(
                source_video=source_video,
                db=db,
                upload_to_facebook=upload_to_facebook,
                num_shorts=num_shorts,
                platforms=resolved_names,
                context_text=f"{source_video.title} {source_video.description or ''}",
                broadcast=broadcast,
                job=process_job,
            )

            source_video.status = VideoStatusEnum.PROCESSED
            self._update_job(
                db, process_job, 100, "Processing complete", JobStatusEnum.COMPLETED
            )
            db.commit()

            # ── Generate source thumbnail ──────────────────────────────────
            if settings.enable_thumbnail_generation:
                try:
                    thumb_path = os.path.join(
                        settings.output_dir, f"{youtube_id}_thumb.jpg"
                    )
                    mid = (source_video.duration_seconds or 60) / 2
                    if self.editor.generate_thumbnail(
                        source_video.local_path, mid, thumb_path
                    ):
                        source_video.thumbnail_path = thumb_path
                        db.commit()
                except Exception as exc:
                    logger.warning("Thumbnail generation failed: %s", exc)

            if broadcast:
                broadcast(
                    {"progress": 100, "stage": "done", "message": "Pipeline complete ✓"}
                )
            logger.info("Pipeline complete for %s", youtube_id)
            return source_video.id

        except Exception as exc:
            logger.error("process_youtube_url error: %s", exc, exc_info=True)
            try:
                if "source_video" in locals() and source_video:
                    source_video.status = VideoStatusEnum.FAILED
                    source_video.error_message = str(exc)
                    db.commit()
            except Exception:
                db.rollback()
            return None

    async def process_youtube_url_async(
        self,
        youtube_url: str,
        db: Session,
        create_shorts: bool = True,
        upload_to_facebook: bool = True,
        num_shorts: int = 3,
        platforms: Optional[List[str]] = None,
        broadcast: Optional[Callable] = None,
    ) -> Optional[str]:
        """Async wrapper — runs synchronous pipeline in a thread pool."""
        return await asyncio.to_thread(
            self.process_youtube_url,
            youtube_url,
            db,
            create_shorts,
            upload_to_facebook,
            num_shorts,
            platforms,
            broadcast,
        )

    # ── Shorts creation ───────────────────────────────────────────────────────

    def _create_and_upload_shorts(
        self,
        source_video: SourceVideo,
        db: Session,
        upload_to_facebook: bool,
        num_shorts: int,
        platforms: List[str],
        context_text: str = "",
        broadcast: Optional[Callable] = None,
        job: Optional[ProcessingJob] = None,
    ) -> None:
        video_path = source_video.local_path
        if not video_path or not os.path.exists(video_path):
            logger.error("Source video path missing: %s", source_video.id)
            return

        segment_pairs = self.editor.extract_short_segments(
            video_path,
            short_duration=settings.short_video_duration,
            num_segments=num_shorts,
            context_text=context_text,
            selection_mode=settings.clip_selection_preset,
        )
        if not segment_pairs:
            logger.warning("No segments extracted for %s", source_video.id)
            return

        variants = self.meta_gen.generate_variants(
            source_title=source_video.title,
            source_description=source_video.description or "",
            variant_count=min(4, max(2, len(segment_pairs))),
        )
        variant_group_id = self._variant_group_id(source_video)
        profiles = resolve_profiles(platforms)

        total = len(segment_pairs) * len(profiles)
        done = 0

        for idx, (start_time, end_time) in enumerate(segment_pairs, 1):
            variant = variants[(idx - 1) % len(variants)]
            base_short_id = f"short_{uuid.uuid4().hex[:12]}"
            duration = int(end_time - start_time)

            for profile in profiles:
                idem_key = self._idempotency_key(
                    source_video.youtube_id, start_time, end_time, profile.name
                )
                if (
                    db.query(ProcessedShort)
                    .filter(ProcessedShort.idempotency_key == idem_key)
                    .first()
                ):
                    logger.info("Skipping existing short for key %s", idem_key)
                    done += 1
                    continue

                short_id = f"{base_short_id}_{profile.name}"
                # Create a compact, human-friendly slug from the source title (fallback to youtube id)
                import re as _re

                title_seed = (source_video.title or source_video.youtube_id)[:120]
                slug = _re.sub(r"[^A-Za-z0-9]+", "-", title_seed).strip("-").lower()
                slug = slug[:48]
                timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

                filename = f"{slug}-{base_short_id}-{profile.name}-{idx:02d}-{timestamp}.{profile.format}"
                short_folder = os.path.join(settings.output_dir, filename.replace(f".{profile.format}", ""))
                os.makedirs(short_folder, exist_ok=True)
                output_path = os.path.join(short_folder, filename)

                # Captions
                caption_file = None
                if settings.enable_auto_subtitles:
                    cap_path = os.path.join(short_folder, f"{base_short_id}.srt")
                    self.caption_gen.generate_best_captions(
                        video_path,
                        cap_path,
                        variant.hook_line,
                        start_time=start_time,
                        duration=duration,
                    )
                    if os.path.exists(cap_path):
                        caption_file = cap_path

                watermark = f"{profile.name.upper()} | ZAPI"
                t0 = time.time()

                pct_done = int(25 + (done / max(total, 1)) * 65)
                if broadcast:
                    broadcast(
                        {
                            "progress": pct_done,
                            "stage": "encode",
                            "message": f"Encoding short {idx}/{len(segment_pairs)} [{profile.name}]…",
                        }
                    )

                success = self.editor.create_short(
                    video_path,
                    output_path,
                    start_time=start_time,
                    duration=duration,
                    add_captions=settings.enable_auto_subtitles and bool(caption_file),
                    caption_file=caption_file,
                    target_width=profile.width,
                    target_height=profile.height,
                    target_fps=profile.fps,
                    target_bitrate=profile.bitrate,
                    watermark_text=watermark,
                )
                encode_time = time.time() - t0

                if not success:
                    logger.error("Failed to encode short %s", short_id)
                    done += 1
                    continue

                # Thumbnail for short
                thumb_path = None
                if settings.enable_thumbnail_generation:
                    thumb_path = output_path.replace(".mp4", "_thumb.jpg")
                    self.editor.generate_thumbnail(
                        output_path, duration / 2, thumb_path
                    )

                processed_short = ProcessedShort(
                    id=short_id,
                    source_video_id=source_video.id,
                    output_path=output_path,
                    output_filename=short_filename,
                    thumbnail_path=(
                        thumb_path
                        if thumb_path and os.path.exists(thumb_path)
                        else None
                    ),
                    duration_seconds=duration,
                    file_size_bytes=(
                        os.path.getsize(output_path)
                        if os.path.exists(output_path)
                        else 0
                    ),
                    resolution=f"{profile.width}x{profile.height}",
                    fps=profile.fps,
                    bitrate=profile.bitrate,
                    has_captions=bool(caption_file),
                    caption_language="en",
                    processing_time_seconds=round(encode_time, 2),
                    status=VideoStatusEnum.PROCESSED,
                    segment_start_seconds=start_time,
                    segment_end_seconds=end_time,
                    segment_number=idx,
                    effects_applied="caption,watermark,fade,loudnorm",
                    platform_profile=profile.name,
                    variant_group_id=variant_group_id,
                    idempotency_key=idem_key,
                    watermark_applied=True,
                    clip_score_data={
                        "hook_line": variant.hook_line,
                        "variant_label": variant.variant_label,
                        "cta_style": variant.cta_style,
                        "platform": profile.name,
                    },
                )
                db.add(processed_short)
                db.commit()
                db.refresh(processed_short)

                # Upload to Facebook if requested
                if upload_to_facebook and profile.name == "facebook_reels":
                    self._upload_short_to_facebook(
                        processed_short=processed_short,
                        source_video=source_video,
                        db=db,
                        variant=variant,
                        platform=profile.name,
                        variant_group_id=variant_group_id,
                        idempotency_key=idem_key,
                    )

                done += 1

    # ── Facebook upload ───────────────────────────────────────────────────────

    def _upload_short_to_facebook(
        self,
        processed_short: ProcessedShort,
        source_video: SourceVideo,
        db: Session,
        variant,
        platform: str,
        variant_group_id: str,
        idempotency_key: str,
    ) -> None:
        if (
            db.query(FacebookUpload)
            .filter(FacebookUpload.idempotency_key == idempotency_key)
            .first()
        ):
            logger.info("Duplicate upload skipped: %s", idempotency_key)
            return
        caption = f"{variant.caption} {' '.join(variant.hashtags)}"
        fb_upload = FacebookUpload(
            id=f"fbup_{uuid.uuid4().hex[:12]}",
            processed_short_id=processed_short.id,
            title=variant.title,
            description=caption,
            status=VideoStatusEnum.UPLOADING,
            platform=platform,
            variant_group_id=variant_group_id,
            variant_label=variant.variant_label,
            cta_style=variant.cta_style,
            idempotency_key=idempotency_key,
            is_winner=False,
        )
        db.add(fb_upload)
        db.commit()
        db.refresh(fb_upload)

        video_id = self.uploader.upload_video(
            processed_short.output_path,
            fb_upload.title,
            fb_upload.description,
            is_reels=True,
        )
        if video_id:
            fb_upload.facebook_video_id = video_id
            fb_upload.status = VideoStatusEnum.UPLOADED
            fb_upload.uploaded_at = datetime.utcnow()
        else:
            fb_upload.status = VideoStatusEnum.FAILED
            fb_upload.error_message = "Upload returned None"
        db.commit()

    # ── Channel processing ────────────────────────────────────────────────────

    def process_channel(
        self,
        channel_url: str,
        db: Session,
        max_videos: Optional[int] = None,
        **kwargs,
    ) -> List[str]:
        """Process all videos from a YouTube channel."""
        results = []
        for video_url in self.downloader.iter_channel_video_urls(
            channel_url, max_videos
        ):
            source_id = self.process_youtube_url(video_url, db, **kwargs)
            if source_id:
                results.append(source_id)
        return results
