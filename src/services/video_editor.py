"""Video editor — FFmpeg pipeline with HW-accel, audio normalisation, thumbnails, effects."""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from src.config.settings import settings
from src.services.clip_scorer import AIClipScoringEngine

logger = logging.getLogger(__name__)


# ── FFmpeg PATH setup ─────────────────────────────────────────────────────────


def _prepend_local_ffmpeg_to_path() -> None:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "tools" / "ffmpeg_new" / "ffmpeg-8.1.1-essentials_build" / "bin",
        project_root / "tools" / "ffmpeg" / "ffmpeg-8.1.1-essentials_build" / "bin",
    ]
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").exists():
            current = os.environ.get("PATH", "")
            if str(candidate) not in current:
                os.environ["PATH"] = str(candidate) + os.pathsep + current
            return


def _detect_hwaccel_encoder() -> Optional[str]:
    """Probe ffmpeg encoders and return the best available HW encoder, or None."""
    if not settings.ffmpeg_use_hwaccel:
        return None
    target = settings.ffmpeg_hwaccel_codec
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if target in result.stdout:
            logger.info("Hardware encoder detected: %s", target)
            return target
    except Exception:
        pass
    return None


class VideoEditor:
    """Full-featured video editor — segmentation, encoding, effects, thumbnails."""

    def __init__(self):
        _prepend_local_ffmpeg_to_path()
        self.output_dir = settings.output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.clip_scorer = AIClipScoringEngine()
        self._hw_encoder: Optional[str] = _detect_hwaccel_encoder()

    # ── Video info ────────────────────────────────────────────────────────────

    def get_video_info(self, video_path: str) -> Optional[dict]:
        """Use ffprobe to get video dimensions, fps, duration."""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate:format=duration",
                "-of",
                "json",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or not result.stdout.strip():
                logger.error("ffprobe failed: %s", result.stderr.strip())
                return None
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            if not streams:
                return None
            s = streams[0]
            fmt = payload.get("format", {})
            fps_raw = s.get("r_frame_rate", "30/1")
            num, den = fps_raw.split("/")
            fps = int(round(float(num) / float(den))) if float(den) else 30
            return {
                "width": int(s.get("width") or 1280),
                "height": int(s.get("height") or 720),
                "fps": fps,
                "duration": float(fmt.get("duration") or 0),
            }
        except Exception as exc:
            logger.error("get_video_info error: %s", exc)
            return None

    def get_audio_loudness(self, video_path: str) -> Optional[float]:
        """Measure integrated loudness in LUFS using EBU R128 via FFmpeg."""
        try:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-i",
                video_path,
                "-af",
                "loudnorm=I=-23:print_format=json",
                "-f",
                "null",
                "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            # loudnorm prints JSON to stderr
            stderr = result.stderr
            start = stderr.rfind("{")
            end = stderr.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(stderr[start:end])
                return float(data.get("input_i", 0))
        except Exception as exc:
            logger.warning("get_audio_loudness error: %s", exc)
        return None

    # ── Scene detection ───────────────────────────────────────────────────────

    def detect_scenes(self, video_path: str, threshold: float = 27.0) -> List[float]:
        """Return timestamps (seconds) of scene changes using FFmpeg scene filter with OpenCV fallback."""
        import re
        # First: try FFmpeg's built-in scene detection at a moderate sensitivity.
        try:
            ffmpeg_bin = "ffmpeg"
            project_root = Path(__file__).resolve().parents[2]
            possible_ffmpeg = (
                project_root
                / "tools"
                / "ffmpeg_new"
                / "ffmpeg-8.1.1-essentials_build"
                / "bin"
                / "ffmpeg.exe"
            )
            if possible_ffmpeg.exists():
                ffmpeg_bin = str(possible_ffmpeg)

            # Use a slightly lower scene threshold to catch subtle cuts, and sample at 5 fps
            # which balances accuracy with speed for long videos. Keep a generous timeout.
            cmd = [
                ffmpeg_bin,
                "-hide_banner",
                "-i",
                video_path,
                "-vf",
                "fps=5,select='gt(scene,0.30)',showinfo",
                "-f",
                "null",
                "-",
            ]
            logger.info(
                "Running FFmpeg scene detector (fps=5,scene>0.30,timeout=%ds)...",
                settings.ffmpeg_scene_detection_timeout_seconds,
            )
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=settings.ffmpeg_scene_detection_timeout_seconds,
            )

            if result.returncode == 0 and result.stderr:
                timestamps = []
                for line in result.stderr.splitlines():
                    if "pts_time:" in line:
                        m = re.search(r"pts_time:([0-9.]+)", line)
                        if m:
                            timestamps.append(float(m.group(1)))
                # If we found an ok number of scene changes, return them
                if len(timestamps) >= 1:
                    logger.info("FFmpeg detected %d scene changes", len(timestamps))
                    return timestamps
                logger.info("FFmpeg returned few scene changes (%d); falling through", len(timestamps))
            else:
                logger.warning(
                    "FFmpeg scene detection failed (rc=%s). Falling back to OpenCV.",
                    result.returncode,
                )
        except Exception as exc:
            logger.warning("FFmpeg scene detection error: %s. Falling back to OpenCV.", exc)

        # --- Robust OpenCV fallback combining color histogram + edge-change ratio ---
        try:
            logger.info("Running enhanced OpenCV scene detector...")
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error("OpenCV cannot open video: %s", video_path)
                return []
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = total_frames / fps if fps > 0 else 0

            # Choose a sampling stride to aim for ~5-8 samples/sec (configurable)
            target_samples_per_sec = 5.0
            stride = max(1, int(round(fps / target_samples_per_sec)))

            hist_diffs: List[float] = []
            edge_diffs: List[float] = []
            times: List[float] = []

            prev_hist = None
            prev_edge = None
            frame_idx = 0
            while frame_idx < total_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break
                # Resize to reasonable processing size
                small = cv2.resize(frame, (480, 270))
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                # 16x8 bins for hue/sat which is fast and effective
                hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
                cv2.normalize(hist, hist)
                # Edge magnitude mean
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                sobelx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
                sobely = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
                edge_mag = np.sqrt(sobelx * sobelx + sobely * sobely)
                edge_mean = float(np.mean(edge_mag))

                if prev_hist is not None:
                    # Bhattacharyya distance for histogram difference
                    diff_hist = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
                    hist_diffs.append(diff_hist)
                    edge_diffs.append(abs(edge_mean - prev_edge))
                    times.append(frame_idx / fps)
                prev_hist = hist
                prev_edge = edge_mean
                frame_idx += stride

            cap.release()

            if not times:
                logger.info("No samples collected for OpenCV detection")
                return []

            # Normalize metrics
            h_arr = np.array(hist_diffs)
            e_arr = np.array(edge_diffs)
            # Combine with weights (hist more important for cuts)
            combined = (h_arr * 0.7) + (e_arr * 0.3)

            # Adaptive threshold: mean + 1.5*std (robust to different content)
            mu = float(np.mean(combined))
            sigma = float(np.std(combined))
            thresh = mu + max(0.02, 1.5 * sigma)

            scene_times: List[float] = []
            min_scene_gap = max(0.5, 0.3 * (1.0))  # in seconds
            last_time = -999.0
            for t, val in zip(times, combined):
                if val >= thresh and (t - last_time) > min_scene_gap:
                    scene_times.append(float(t))
                    last_time = t

            logger.info(
                "OpenCV detector: samples=%d, scenes=%d, thresh=%.4f", len(times), len(scene_times), thresh
            )
            return scene_times
        except Exception as exc:
            logger.error("Enhanced OpenCV detect_scenes error: %s", exc, exc_info=True)
            return []

    # ── Segment extraction ────────────────────────────────────────────────────

    def extract_short_segments(
        self,
        video_path: str,
        short_duration: int = 210,
        num_segments: int = 3,
        context_text: str = "",
        selection_mode: Optional[str] = None,
    ) -> List[Tuple[float, float]]:
        """Extract segments.

        Behavior:
        - selection_mode == "easy_best" (or None): fast uniform sampling (original fast path)
        - selection_mode in {"best", "balanced"}: run scene detection, generate candidates around scene cuts,
          then score them with `AIClipScoringEngine` and return top-ranked segments.
        """
        try:
            info = self.get_video_info(video_path)
            if not info:
                return []
            total = info["duration"]
            if total <= 0:
                return []
            if total < short_duration:
                return [(0, total)]

            mode = selection_mode or "easy_best"

            # Fast path (legacy behavior)
            if mode == "easy_best":
                candidates: List[Tuple[float, float]] = []
                step = total / (num_segments + 1)
                for i in range(num_segments):
                    anchor = step * (i + 1)
                    start = max(0, anchor - short_duration / 2)
                    end = min(total, start + short_duration)
                    if end - start >= short_duration * 0.8:
                        candidates.append((start, end))

                if len(candidates) < num_segments:
                    for offset in [0, total * 0.1, total * 0.2, total * 0.3]:
                        start = max(0, offset)
                        end = min(total, start + short_duration)
                        if (
                            end - start >= short_duration * 0.8
                            and (start, end) not in candidates
                        ):
                            candidates.append((start, end))

                # Deduplicate by proximity
                unique: List[Tuple[float, float]] = []
                for s, e in candidates:
                    if not any(
                        abs(s - us) < (short_duration * 0.3) for us, ue in unique
                    ):
                        unique.append((s, e))
                return unique[:num_segments]

            # Advanced path: scene detection + scoring
            scene_timestamps = self.detect_scenes(video_path)
            candidates: List[Tuple[float, float]] = []

            # Build candidates around each scene cut (center segments on cuts)
            for ts in scene_timestamps:
                start = max(0.0, ts - short_duration / 2)
                end = min(total, start + short_duration)
                if end - start >= short_duration * 0.6:
                    candidates.append((start, end))

            # Add uniform anchors as fallback
            step = total / (max(4, num_segments + 2))
            for i in range(max(3, num_segments)):
                anchor = step * (i + 1)
                start = max(0, anchor - short_duration / 2)
                end = min(total, start + short_duration)
                if end - start >= short_duration * 0.6:
                    candidates.append((start, end))

            # Normalize and deduplicate candidates by rounding start to 0.1s and removing near-duplicates
            seen = set()
            normalized: List[Tuple[float, float]] = []
            for s, e in candidates:
                key = round(s, 1)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append((s, e))

            if not normalized:
                return []

            # Score candidates using clip scorer and return top N
            try:
                scored = self.clip_scorer.rank_segments(
                    video_path,
                    normalized,
                    context_text=context_text or "",
                    selection_mode=mode,
                )
                top = [(c.start, c.end) for c in scored[:num_segments]]
                # As a final safety, ensure segments are within video bounds
                final = [(max(0.0, s), min(total, e)) for s, e in top]
                return final
            except Exception as exc:
                logger.warning(
                    "Scoring failed, falling back to uniform segments: %s", exc
                )
                # Fallback: uniform distribution
                step = total / (num_segments + 1)
                fallback: List[Tuple[float, float]] = []
                for i in range(num_segments):
                    anchor = step * (i + 1)
                    start = max(0, anchor - short_duration / 2)
                    end = min(total, start + short_duration)
                    fallback.append((start, end))
                return fallback
        except Exception as exc:
            logger.error("extract_short_segments error: %s", exc)
            return []

    # ── Short creation ────────────────────────────────────────────────────────

    def create_short(
        self,
        video_path: str,
        output_path: str,
        start_time: float = 0,
        duration: int = 210,
        add_captions: bool = False,
        caption_file: Optional[str] = None,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        target_fps: Optional[int] = None,
        target_bitrate: Optional[str] = None,
        watermark_text: Optional[str] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> bool:
        """Encode a short clip with optional captions, watermark, audio norm, and fade effects."""
        try:
            w = target_width or settings.output_width
            h = target_height or settings.output_height
            fps = target_fps or settings.output_fps
            bitrate = target_bitrate or settings.output_bitrate

            logger.info("Creating short: %s [%ds @ %s]", output_path, duration, bitrate)

            # Build video filter chain
            vf_parts = [
                f"scale={w}:{h}:force_original_aspect_ratio=increase",
                f"crop={w}:{h}",
                f"fps={fps}",
            ]

            # FAST MODE: Skip fade effects
            if add_captions and caption_file and os.path.exists(caption_file):
                escaped = caption_file.replace("\\", "/").replace(":", "\\:")
                vf_parts.append(f"subtitles={escaped}")

            vf = ",".join(vf_parts)

            # Check if logo file exists in static dir - try multiple paths
            logo_paths = [
                os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    "api",
                    "static",
                    "logo.png",
                ),
                os.path.join(os.getcwd(), "src", "api", "static", "logo.png"),
                "src/api/static/logo.png",
            ]
            logo_path = None
            for path in logo_paths:
                if os.path.exists(path):
                    logo_path = os.path.abspath(path)
                    break
            has_logo = logo_path is not None

            if has_logo:
                logger.info(f"Logo detected at: {logo_path}")
            else:
                logger.warning("Logo file not found in any of the expected locations")

            inputs = ["-ss", str(start_time), "-i", video_path]
            filter_flags = []

            if has_logo:
                inputs.extend(["-i", logo_path])
                # Overlay logo at top-right corner with original 180x180 size and positioning
                filter_flags = [
                    "-filter_complex",
                    f"[0:v]{vf}[main];[1:v]scale=180:180[logo];[main][logo]overlay=main_w-overlay_w-40:40",
                ]
            else:
                filter_flags = ["-vf", vf]

            # FAST MODE: Skip audio normalization
            af_flags: list = []

            # Choose encoder
            vcodec = self._hw_encoder or settings.output_codec
            preset_flag = (
                [] if self._hw_encoder else ["-preset", settings.output_preset]
            )

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                *inputs,
                "-t",
                str(duration),
                *filter_flags,
                "-b:v",
                bitrate,
                "-c:v",
                vcodec,
                *preset_flag,
                *af_flags,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-y",
                output_path,
            ]

            logger.debug("FFmpeg cmd: %s", " ".join(cmd[:15]))

            # (no debug file writes) keep only in-memory logging of the command

            # Log filter details
            if has_logo:
                filter_idx = next(
                    (i for i, x in enumerate(cmd) if x == "-filter_complex"), None
                )
                if filter_idx:
                    logger.info(
                        f"Using filter_complex with logo overlay: {cmd[filter_idx+1][:100]}..."
                    )
            else:
                vf_idx = next((i for i, x in enumerate(cmd) if x == "-vf"), None)
                if vf_idx:
                    logger.info(f"Using simple video filter: {cmd[vf_idx+1]}")
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            # Parse progress lines
            total_us = duration * 1_000_000
            captured_lines = []
            for line in proc.stdout:
                line = line.strip()
                captured_lines.append(line)
                if line.startswith("out_time_us="):
                    try:
                        elapsed_us = int(line.split("=")[1])
                        pct = min(100.0, elapsed_us / total_us * 100)
                        if progress_callback:
                            progress_callback(pct)
                    except ValueError:
                        pass
            proc.wait(timeout=300)

            # keep captured_lines in memory for logging below if needed

            if proc.returncode != 0:
                err = "\n".join(captured_lines)
                # Fallback to libx264 if HW encoder failed
                if self._hw_encoder:
                    logger.warning(
                        "Hardware encoder '%s' failed, falling back to libx264. Error details: %s",
                        self._hw_encoder,
                        err[:400],
                    )
                    self._hw_encoder = None
                    return self.create_short(
                        video_path,
                        output_path,
                        start_time,
                        duration,
                        add_captions,
                        caption_file,
                        w,
                        h,
                        fps,
                        bitrate,
                        watermark_text,
                        progress_callback,
                    )
                logger.error("FFmpeg failed (rc=%d): %s", proc.returncode, err[:500])
                return False

            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
                logger.error("Output file missing or empty: %s", output_path)
                return False

            size = os.path.getsize(output_path)
            logger.info("Short created: %.1f MB", size / 1_048_576)
            return True

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timed out encoding %s", output_path)
            return False
        except Exception as exc:
            logger.error("create_short error: %s", exc, exc_info=True)
            return False

    # ── Thumbnail generation ──────────────────────────────────────────────────

    def generate_thumbnail(
        self, video_path: str, timestamp: float, output_path: str
    ) -> bool:
        """Extract a single frame as JPEG thumbnail using ffmpeg."""
        try:
            cmd = [
                "ffmpeg",
                "-ss",
                str(timestamp),
                "-i",
                video_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-vf",
                "scale=1080:-1",
                "-y",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return result.returncode == 0 and os.path.exists(output_path)
        except Exception as exc:
            logger.error("generate_thumbnail error: %s", exc)
            return False

    # ── Effects ───────────────────────────────────────────────────────────────

    def add_effects(
        self, video_path: str, output_path: str, effect_type: str = "fade"
    ) -> bool:
        """Apply a named visual effect to a video file."""
        try:
            if effect_type == "fade":
                vf = "fade=t=in:st=0:d=0.5,fade=t=out:st=58:d=1"
            elif effect_type == "zoom":
                vf = "zoompan=z='min(zoom+0.0005,1.05)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',fps=30"
            else:
                vf = "fps=30"

            cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "copy",
                "-y",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return result.returncode == 0
        except Exception as exc:
            logger.error("add_effects error: %s", exc)
            return False

    def add_intro_outro(
        self,
        main_path: str,
        output_path: str,
        intro_path: Optional[str] = None,
        outro_path: Optional[str] = None,
    ) -> bool:
        """Concatenate intro + main + outro into a single file."""
        try:
            parts = []
            if intro_path and os.path.exists(intro_path):
                parts.append(intro_path)
            parts.append(main_path)
            if outro_path and os.path.exists(outro_path):
                parts.append(outro_path)

            if len(parts) == 1:
                import shutil as _sh

                _sh.copy2(main_path, output_path)
                return True

            # Write concat list
            list_path = output_path + "_concat.txt"
            with open(list_path, "w") as f:
                for p in parts:
                    safe_p = p.replace("'", "'\\''")
                    f.write(f"file '{safe_p}'\n")

            cmd = [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_path,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-y",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            try:
                os.unlink(list_path)
            except OSError:
                pass
            return result.returncode == 0
        except Exception as exc:
            logger.error("add_intro_outro error: %s", exc)
            return False
