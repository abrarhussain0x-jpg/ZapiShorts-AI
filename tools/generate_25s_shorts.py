#!/usr/bin/env python3
"""Generate organized 25s shorts from a source video.

Creates three folders under `data/output/`:
- `25s_best_hooks` — ranked by hook strength
- `25s_best_overall` — ranked by overall score
- `25s_varied` — uniform sampling for variety

Usage: run from repo root:
    python tools/generate_25s_shorts.py "data/downloads/your_video.mp4"

"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

# Ensure repository root is on sys.path so `src` package imports work
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from src.config.settings import settings
from src.services.clip_scorer import AIClipScoringEngine
from src.services.video_editor import VideoEditor


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def sliding_windows(
    duration: float, window: int = 25, step: int = 12, max_windows: int = 200
) -> List[Tuple[float, float]]:
    windows = []
    start = 0.0
    while start + window <= duration and len(windows) < max_windows:
        windows.append((start, start + window))
        start += step
    # If not enough windows, add tail windows
    if not windows and duration > 0:
        windows.append((0.0, min(window, duration)))
    return windows


def pick_top_nonoverlapping(scores, top_n=5, min_separation=8.0):
    chosen = []
    for s in scores:
        if len(chosen) >= top_n:
            break
        start = s.start
        ok = True
        for c in chosen:
            if abs(start - c.start) < min_separation:
                ok = False
                break
        if ok:
            chosen.append(s)
    return chosen


def make_clean_name(video_path: Path, short_type: str, idx: int) -> str:
    stem = video_path.stem.replace(" ", "_").lower()
    return f"{stem}__25s__{short_type}__{idx:02d}.mp4"


def generate_for_video(video_path: str, per_folder: int = 5):
    ve = VideoEditor()
    scorer = AIClipScoringEngine()
    info = ve.get_video_info(video_path)
    if not info:
        print("Cannot read video info")
        return
    duration = info["duration"]

    out_base = Path(settings.output_dir)
    folders = {
        "best_hooks": out_base / "25s_best_hooks",
        "best_overall": out_base / "25s_best_overall",
        "varied": out_base / "25s_varied",
    }
    for p in folders.values():
        ensure_dir(p)

    # 1) Best hooks — sliding windows scored by hook_strength / easy_best
    candidates = sliding_windows(duration, window=25, step=8, max_windows=300)
    scored = scorer.rank_segments(
        video_path, candidates, selection_mode="easy_best", max_workers=4
    )
    chosen = pick_top_nonoverlapping(scored, top_n=per_folder, min_separation=10.0)
    for i, s in enumerate(chosen, start=1):
        out = folders["best_hooks"] / make_clean_name(Path(video_path), "best_hook", i)
        print(f"Creating best_hook short {i}: {s.start:.1f}-{s.end:.1f} -> {out}")
        ve.create_short(video_path, str(out), start_time=s.start, duration=25)

    # 2) Best overall — selection_mode 'best'
    scored2 = scorer.rank_segments(
        video_path, candidates, selection_mode="best", max_workers=4
    )
    chosen2 = pick_top_nonoverlapping(scored2, top_n=per_folder, min_separation=10.0)
    for i, s in enumerate(chosen2, start=1):
        out = folders["best_overall"] / make_clean_name(
            Path(video_path), "best_overall", i
        )
        print(f"Creating best_overall short {i}: {s.start:.1f}-{s.end:.1f} -> {out}")
        ve.create_short(video_path, str(out), start_time=s.start, duration=25)

    # 3) Varied — uniform sampling using extract_short_segments
    varied_segments = ve.extract_short_segments(
        video_path, short_duration=25, num_segments=per_folder
    )
    for i, (s_start, s_end) in enumerate(varied_segments, start=1):
        out = folders["varied"] / make_clean_name(Path(video_path), "varied", i)
        print(f"Creating varied short {i}: {s_start:.1f}-{s_end:.1f} -> {out}")
        ve.create_short(video_path, str(out), start_time=s_start, duration=25)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python tools/generate_25s_shorts.py <video_path> [per_folder_count]"
        )
        sys.exit(1)
    video = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    generate_for_video(video, per_folder=per)
