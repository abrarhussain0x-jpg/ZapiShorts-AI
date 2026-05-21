"""AI clip scoring — motion, speech, hook, face detection, audio energy, parallel scoring."""

import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ClipScore:
    start: float
    end: float
    hook_strength: float
    motion: float
    speech_density: float
    sentiment: float
    face_presence: float
    audio_energy: float
    total: float


class AIClipScoringEngine:
    """Multi-signal clip scorer with parallel evaluation."""

    MODE_WEIGHTS: Dict[str, Dict[str, float]] = {
        "easy_best": {
            "hook": 0.35,
            "motion": 0.15,
            "speech": 0.20,
            "sentiment": 0.10,
            "face": 0.10,
            "audio": 0.05,
            "length": 0.05,
        },
        "best": {
            "hook": 0.30,
            "motion": 0.25,
            "speech": 0.15,
            "sentiment": 0.08,
            "face": 0.12,
            "audio": 0.05,
            "length": 0.05,
        },
        "balanced": {
            "hook": 0.25,
            "motion": 0.20,
            "speech": 0.20,
            "sentiment": 0.10,
            "face": 0.10,
            "audio": 0.10,
            "length": 0.05,
        },
    }

    POSITIVE_WORDS = {
        "best",
        "amazing",
        "viral",
        "secret",
        "top",
        "win",
        "growth",
        "learn",
        "insane",
        "must",
        "powerful",
        "proven",
        "breakthrough",
        "success",
        "easy",
        "shocking",
        "incredible",
        "exclusive",
        "hidden",
        "ultimate",
    }
    NEGATIVE_WORDS = {"boring", "slow", "bad", "fail", "worse", "mistake", "problem"}

    _face_cascade: Optional[cv2.CascadeClassifier] = None

    @classmethod
    def _get_face_cascade(cls) -> Optional[cv2.CascadeClassifier]:
        if cls._face_cascade is None:
            xml = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            cls._face_cascade = cv2.CascadeClassifier(xml)
        return cls._face_cascade

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _norm(self, value: float, max_val: float) -> float:
        if max_val <= 0:
            return 0.0
        return max(0.0, min(1.0, value / max_val))

    # ── Individual signals ────────────────────────────────────────────────────

    def _length_score(self, start: float, end: float, mode: str) -> float:
        duration = max(0.1, end - start)
        ideal = {"easy_best": 30.0, "best": 45.0, "balanced": 40.0}.get(mode, 30.0)
        return max(0.0, min(1.0, 1.0 - abs(duration - ideal) / 30.0))

    def _motion_score(self, video_path: str, start: float, end: float) -> float:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = int(start * fps)
        end_frame = int(end * fps)

        # Sample at most 30 frames evenly distributed to avoid massive seek times on long videos
        num_samples = 30
        frame_indices = np.linspace(start_frame, end_frame, num_samples, dtype=int)

        prev, diffs = None, []
        for frame_num in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_num))
            ret, img = cap.read()
            if not ret:
                break
            small = cv2.resize(img, (240, 135))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            if prev is not None:
                diffs.append(float(np.mean(cv2.absdiff(gray, prev))))
            prev = gray
        cap.release()
        return self._norm(float(np.mean(diffs)) if diffs else 0.0, 40.0)

    def _face_score(self, video_path: str, start: float, end: float) -> float:
        """Score based on face presence (human faces = more engaging)."""
        cascade = self._get_face_cascade()
        if cascade is None or cascade.empty():
            return 0.5
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 0.5
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        sample_times = [start, (start + end) / 2, end - 1]
        face_counts = []
        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                continue
            gray = cv2.cvtColor(cv2.resize(frame, (480, 270)), cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
            )
            face_counts.append(len(faces))
        cap.release()
        avg_faces = np.mean(face_counts) if face_counts else 0
        return min(1.0, avg_faces / 2.0)  # normalise: 2+ faces → 1.0

    def _audio_energy_score(self, video_path: str, start: float, end: float) -> float:
        """Score based on audio RMS energy using ffmpeg astats."""
        duration = max(0.1, end - start)
        eval_duration = min(30.0, duration)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(eval_duration),
            "-i",
            video_path,
            "-af",
            "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            matches = re.findall(r"RMS_level=(-?[\d.]+)", proc.stderr)
            if matches:
                avg_rms = float(np.mean([float(m) for m in matches]))
                # RMS level in dBFS, typically -60 to 0; map to 0-1
                return max(0.0, min(1.0, (avg_rms + 60) / 60.0))
        except Exception:
            pass
        return 0.5

    def _spectral_flux_score(self, video_path: str, start: float, end: float) -> float:
        """Estimate spectral flux from short audio segment using ffmpeg astats RMS_level stream.

        Returns 0-1 where higher values indicate rapid increases in energy (punchy content).
        """
        duration = max(0.1, end - start)
        eval_duration = min(10.0, duration)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(eval_duration),
            "-i",
            video_path,
            "-af",
            "astats=metadata=1:reset=1",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            # Extract RMS_level occurrences
            rms_vals = [float(v) for v in re.findall(r"RMS_level=(-?[0-9.]+)", proc.stderr)]
            if len(rms_vals) < 2:
                return 0.5
            diffs = np.diff(rms_vals)
            # consider only positive increases as flux
            pos = np.sum(np.clip(diffs, a_min=0, a_max=None))
            # normalize: typical RMS diffs in dB; divide by a heuristic scale
            score = float(pos) / max(1.0, len(diffs) * 2.0)
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5

    def _voice_onset_score(self, video_path: str, start: float, end: float) -> float:
        """Estimate number of voice onsets (silence_end events) in the early part of a segment.

        Returns 0-1 normalized by expected useful onsets (3).
        """
        duration = max(0.1, end - start)
        eval_duration = min(6.0, duration)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-ss",
            str(start),
            "-t",
            str(eval_duration),
            "-i",
            video_path,
            "-af",
            "silencedetect=noise=-30dB:d=0.25",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            log = proc.stderr
            # Count silence_end occurrences (voice onsets)
            onsets = len(re.findall(r"silence_end: [0-9.]+", log))
            return max(0.0, min(1.0, onsets / 3.0))
        except Exception:
            return 0.5

    def _hook_strength_score(
        self, video_path: str, start: float, context_text: str
    ) -> float:
        """Deep multivariable hook strength evaluation (100x best deep top tier).
        Combines early visual motion, vocal presence punch, scene cut detection,
        and high-impact psychological text triggers.
        """
        # 1. Early Visual Motion (0-3s)
        early_motion = self._motion_score(video_path, start, start + 3.0)

        # 2. Vocal Punch (0-3s speech density - checks if voice is active immediately without silence)
        early_speech = self._speech_density_score(video_path, start, start + 3.0)

        # 3. Audio Energy (0-3s RMS volume punch)
        early_audio = self._audio_energy_score(video_path, start, start + 3.0)

        # 4. Spectral flux (rapid energy changes) and voice onsets
        early_flux = self._spectral_flux_score(video_path, start, start + 3.0)
        early_onset = self._voice_onset_score(video_path, start, start + 3.0)

        # 4. Psychological & Viral Text Hook Trigger Scoring
        tokens = {
            # Curiosity & Intrigue (Weight: 1.0)
            "secret": 1.0,
            "reveal": 1.0,
            "exposed": 1.0,
            "hidden": 1.0,
            "confession": 1.0,
            "never seen": 1.0,
            "uncovered": 1.0,
            "expose": 1.0,
            "what happened": 1.0,
            "don't want you": 1.0,
            # Extreme Value & Wealth (Weight: 1.0)
            "insane": 1.0,
            "millionaire": 1.0,
            "rich": 1.0,
            "poor": 1.0,
            "copied": 1.0,
            "overnight": 1.0,
            "hacks": 1.0,
            "tricks": 1.0,
            "goldmine": 1.0,
            "viral": 1.0,
            "life changing": 1.0,
            "cheat": 1.0,
            # Urgency & Warning (Weight: 0.9)
            "stop": 0.9,
            "wait": 0.9,
            "warning": 0.9,
            "alert": 0.9,
            "danger": 0.9,
            "look": 0.9,
            "shocking": 0.9,
            "incredible": 0.9,
            "unbelievable": 0.9,
            "must watch": 0.9,
            # Authority & Excellence (Weight: 0.8)
            "best": 0.8,
            "top 10": 0.8,
            "proven": 0.8,
            "formula": 0.8,
            "guaranteed": 0.8,
            "expert": 0.8,
        }

        context_lower = (context_text or "").lower()
        matched_weights = [
            weight for token, weight in tokens.items() if token in context_lower
        ]

        if matched_weights:
            # Compound score if multiple hooks exist
            text_hook = min(
                1.0,
                sum(matched_weights) / max(1, len(matched_weights))
                + 0.1 * (len(matched_weights) - 1),
            )
        else:
            text_hook = 0.35  # default baseline text hook

        # 5. Composite Deep Score
        # Add spectral flux and voice onset signals to better capture punchy openings.
        # New weights: motion 30%, speech 18%, audio 12%, flux 10%, onset 5%, text 25%
        hook_score = (
            0.30 * early_motion
            + 0.18 * early_speech
            + 0.12 * early_audio
            + 0.10 * early_flux
            + 0.05 * early_onset
            + 0.25 * text_hook
        )

        logger.info(
            "Deep Hook Score at %.1fs: %.4f [Motion: %.2f, Speech: %.2f, Audio: %.2f, Text: %.2f]",
            start,
            hook_score,
            early_motion,
            early_speech,
            early_audio,
            text_hook,
        )
        return max(0.0, min(1.0, hook_score))

    def _speech_density_score(self, video_path: str, start: float, end: float) -> float:
        duration = max(0.1, end - start)
        eval_duration = min(45.0, duration)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-ss",
            str(start),
            "-t",
            str(eval_duration),
            "-i",
            video_path,
            "-af",
            "silencedetect=noise=-30dB:d=0.35",
            "-f",
            "null",
            "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            log = proc.stderr
            starts = [float(v) for v in re.findall(r"silence_start: ([\d.]+)", log)]
            ends = [float(v) for v in re.findall(r"silence_end: ([\d.]+)", log)]
            silence = sum(
                max(0.0, (ends[i] if i < len(ends) else eval_duration) - s)
                for i, s in enumerate(starts)
            )
            return max(0.0, min(1.0, (eval_duration - silence) / eval_duration))
        except Exception:
            return 0.5

    def _sentiment_score(self, context_text: str) -> float:
        words = re.sub(r"[^a-zA-Z0-9\s]", " ", (context_text or "").lower()).split()
        if not words:
            return 0.5
        pos = sum(1 for w in words if w in self.POSITIVE_WORDS)
        neg = sum(1 for w in words if w in self.NEGATIVE_WORDS)
        return max(0.0, min(1.0, 0.5 + (pos - neg) / max(6, len(words))))

    # ── Single segment scoring ────────────────────────────────────────────────

    def score_segment(
        self,
        video_path: str,
        start: float,
        end: float,
        context_text: str = "",
        selection_mode: str = "easy_best",
    ) -> ClipScore:
        mode = selection_mode if selection_mode in self.MODE_WEIGHTS else "easy_best"
        w = self.MODE_WEIGHTS[mode]

        hook = self._hook_strength_score(video_path, start, context_text)
        motion = self._motion_score(video_path, start, end)
        speech = self._speech_density_score(video_path, start, end)
        sentiment = self._sentiment_score(context_text)
        face = self._face_score(video_path, start, end)
        audio = self._audio_energy_score(video_path, start, end)
        length = self._length_score(start, end, mode)

        total = (
            w["hook"] * hook
            + w["motion"] * motion
            + w["speech"] * speech
            + w["sentiment"] * sentiment
            + w["face"] * face
            + w["audio"] * audio
            + w["length"] * length
        )
        return ClipScore(
            start, end, hook, motion, speech, sentiment, face, audio, total
        )

    def explain_score(self, score: ClipScore) -> Dict[str, float]:
        return {
            "hook_strength": round(score.hook_strength, 4),
            "motion": round(score.motion, 4),
            "speech_density": round(score.speech_density, 4),
            "sentiment": round(score.sentiment, 4),
            "face_presence": round(score.face_presence, 4),
            "audio_energy": round(score.audio_energy, 4),
            "total": round(score.total, 4),
        }

    # ── Parallel ranking ──────────────────────────────────────────────────────

    def rank_segments(
        self,
        video_path: str,
        segments: List[Tuple[float, float]],
        context_text: str = "",
        selection_mode: str = "easy_best",
        max_workers: int = 4,
    ) -> List[ClipScore]:
        """Score all segments in parallel using a thread pool."""
        scores: List[ClipScore] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.score_segment, video_path, s, e, context_text, selection_mode
                ): (s, e)
                for s, e in segments
            }
            for future in as_completed(futures):
                try:
                    scores.append(future.result())
                except Exception as exc:
                    s, e = futures[future]
                    logger.warning("Scoring failed for %.1f-%.1f: %s", s, e, exc)
        return sorted(scores, key=lambda x: x.total, reverse=True)
