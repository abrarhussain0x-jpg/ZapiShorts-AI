"""Caption generator — mock, OpenAI Whisper (API), and faster-whisper (local)."""

import logging
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from src.config.settings import settings

logger = logging.getLogger(__name__)


def _srt_time(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    ms = int((td.total_seconds() % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(segments: List[Tuple[float, float, str]], output_path: str) -> bool:
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for idx, (start, end, text) in enumerate(segments, 1):
                f.write(
                    f"{idx}\n{_srt_time(start)} --> {_srt_time(end)}\n{text.strip()}\n\n"
                )
        return True
    except OSError as exc:
        logger.error("_write_srt failed: %s", exc)
        return False


class CaptionGenerator:
    """Generate and burn captions with multiple backends."""

    # Class-level Whisper model cache — loaded once, reused across all clips.
    # Using a class attribute avoids reloading the model (which takes 2-10 s)
    # every time a new short is generated.
    _cached_whisper_model = None
    _cached_whisper_model_name: str = ""

    def __init__(self):
        self.output_dir = settings.output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def time_to_srt_format(seconds: float) -> str:
        return _srt_time(seconds)

    # ── Local Whisper model cache ──────────────────────────────────────────────

    @classmethod
    def _get_local_whisper_model(cls):
        """Return the cached standard-whisper model, loading it on first call."""
        model_name = settings.local_whisper_model
        if (
            cls._cached_whisper_model is None
            or cls._cached_whisper_model_name != model_name
        ):
            import whisper as _whisper

            logger.info(
                "Loading Whisper model '%s' (first use — will be cached)...", model_name
            )
            cls._cached_whisper_model = _whisper.load_model(model_name, device="cpu")
            cls._cached_whisper_model_name = model_name
            logger.info("Whisper model '%s' loaded and cached.", model_name)
        return cls._cached_whisper_model

    # ── Mock captions ─────────────────────────────────────────────────────────

    def create_mock_captions(
        self,
        video_duration: float,
        output_path: str,
        text: str = "Amazing content! #Shorts",
    ) -> bool:
        """Generate placeholder captions — used when no speech-to-text backend is available."""
        hooks = [
            "Amazing Content!",
            "Watch till the end 👀",
            "You won't believe this...",
            "Drop a like ❤️",
            "Follow for more 🔥",
            f"{text[:60]}",
        ]
        seg_len = min(10, video_duration / max(len(hooks), 1))
        segments: List[Tuple[float, float, str]] = []
        for i, hook in enumerate(hooks):
            start = i * seg_len
            if start >= video_duration:
                break
            end = min(start + seg_len, video_duration)
            segments.append((start, end, hook))

        return _write_srt(segments, output_path)

    # ── Audio extraction ──────────────────────────────────────────────────────

    def extract_audio(
        self,
        video_path: str,
        output_path: str,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
    ) -> bool:
        """Extract audio track to MP3, optionally starting at start_time for duration seconds."""
        try:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
            if start_time is not None:
                cmd.extend(["-ss", str(start_time)])
            if duration is not None:
                cmd.extend(["-t", str(duration)])
            cmd.extend(
                [
                    "-i",
                    video_path,
                    "-vn",
                    "-q:a",
                    "4",
                    "-c:a",
                    "libmp3lame",
                    "-y",
                    output_path,
                ]
            )
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0 and os.path.exists(output_path)
        except Exception as exc:
            logger.error("extract_audio error: %s", exc)
            return False

    # ── OpenAI Whisper (API) ──────────────────────────────────────────────────

    def generate_captions_with_openai(
        self, audio_path: str, output_path: str, language: str = "en"
    ) -> bool:
        """Transcribe audio via OpenAI Whisper API and write SRT."""
        if not settings.openai_api_key:
            logger.warning("OpenAI API key not set — skipping Whisper")
            return False
        if not settings.enable_real_whisper:
            return False
        try:
            from openai import OpenAI

            client = OpenAI(api_key=settings.openai_api_key)
            with open(audio_path, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model=settings.openai_whisper_model,
                    file=f,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            segs = getattr(transcript, "segments", []) or []
            segments = [(s.start, s.end, s.text) for s in segs]
            if not segments:
                logger.warning("Whisper returned empty segments")
                return False
            logger.info("OpenAI Whisper: %d segments for %s", len(segments), audio_path)
            return _write_srt(segments, output_path)
        except Exception as exc:
            logger.error("generate_captions_with_openai error: %s", exc, exc_info=True)
            return False

    # ── Local Whisper (faster-whisper or standard whisper) ────────────────────

    def generate_captions_local(
        self, audio_path: str, output_path: str, language: str = "en"
    ) -> bool:
        """Transcribe using standard whisper or faster-whisper (no API key required)."""
        if not settings.enable_local_whisper:
            return False

        # 1. Try standard openai-whisper via the cached model instance.
        try:
            model = self._get_local_whisper_model()
            logger.info("Transcribing segment audio via cached standard Whisper...")
            result = model.transcribe(audio_path, language=language)
            segments = [
                (s["start"], s["end"], s["text"]) for s in result.get("segments", [])
            ]
            logger.info("Standard Whisper completed: %d segments", len(segments))
            if segments:
                return _write_srt(segments, output_path)
        except ImportError:
            logger.info("Standard whisper package not found, trying faster-whisper...")
        except Exception as exc:
            logger.warning(
                "Standard whisper transcription failed: %s, trying faster-whisper...",
                exc,
            )

        # 2. Fallback to faster-whisper (no class-level cache — it manages its own state).
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                settings.local_whisper_model, device="cpu", compute_type="int8"
            )
            segments_iter, _ = model.transcribe(audio_path, language=language)
            segments = [(s.start, s.end, s.text) for s in segments_iter]
            logger.info("Local faster-whisper: %d segments", len(segments))
            return _write_srt(segments, output_path)
        except ImportError:
            logger.warning(
                "Neither standard whisper nor faster-whisper is installed — skipping local transcription"
            )
            return False
        except Exception as exc:
            logger.error("generate_captions_local error: %s", exc, exc_info=True)
            return False

    # ── Auto-select backend ───────────────────────────────────────────────────

    def generate_best_captions(
        self,
        video_path: str,
        output_path: str,
        hook_text: str = "",
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
    ) -> bool:
        """Try OpenAI → local Whisper → mock, in that priority order."""
        audio_path = output_path.replace(".srt", "_audio.mp3")
        audio_created = False
        try:
            if settings.enable_real_whisper and settings.openai_api_key:
                audio_created = self.extract_audio(
                    video_path, audio_path, start_time, duration
                )
                if audio_created and self.generate_captions_with_openai(
                    audio_path, output_path
                ):
                    return True

            if settings.enable_local_whisper:
                if not audio_created:
                    audio_created = self.extract_audio(
                        video_path, audio_path, start_time, duration
                    )
                if audio_created and self.generate_captions_local(
                    audio_path, output_path
                ):
                    return True
        finally:
            # Only delete the temp audio file if it was actually created.
            if audio_created and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        return self.create_mock_captions(duration or 60, output_path, hook_text)

    # ── Burn captions into video ──────────────────────────────────────────────

    def burn_captions_styled(
        self,
        video_path: str,
        srt_path: str,
        output_path: str,
        style: str = "viral_premium",
    ) -> bool:
        """Burn captions with a named visual style."""
        style_filters = {
            "centered_white": "subtitles={srt}:force_style='Alignment=2,Fontsize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3'",
            "tiktok_yellow": "subtitles={srt}:force_style='Alignment=2,Fontsize=22,PrimaryColour=&H00FFFF,Bold=1,OutlineColour=&H000000,BorderStyle=3'",
            "bottom_bold": "subtitles={srt}:force_style='Alignment=2,Fontsize=20,Bold=1,PrimaryColour=&HFFFFFF,OutlineColour=&H000000'",
            "viral_premium": "subtitles={srt}:force_style='Alignment=2,Fontname=Impact,Fontsize=20,PrimaryColour=&H00FFFF,OutlineColour=&H80000000,BorderStyle=3,MarginV=90'",
        }
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
        vf = style_filters.get(style, style_filters["viral_premium"]).format(
            srt=srt_escaped
        )
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-vf",
                    vf,
                    "-c:a",
                    "copy",
                    "-y",
                    output_path,
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.error("burn_captions_styled error: %s", exc)
            return False

    def add_captions_to_video(
        self, video_path: str, captions_path: str, output_path: str
    ) -> bool:
        return self.burn_captions_styled(
            video_path, captions_path, output_path, style="viral_premium"
        )
