"""Download the latest video from a channel and run the CLI process command to create shorts.
Usage: python tools/run_channel_process.py [channel_url]

This script uses the project's `YouTubeDownloader` and `cli.py` to find the latest
video URL from a channel and call the `process` CLI command with `--no-upload`.
"""

import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.config.settings import settings
from src.services.youtube_downloader import YouTubeDownloader

CHANNEL_DEFAULT = (
    settings.youtube_channel_ids[0]
    if settings.youtube_channel_ids
    else "https://youtube.com/@storylinemovie?si=QGRjhms7zIYCyLa6"
)


def main():
    channel = sys.argv[1] if len(sys.argv) > 1 else CHANNEL_DEFAULT
    print(f"Using channel: {channel}")
    dl = YouTubeDownloader()
    video_url = None
    for candidate_url in dl.iter_channel_video_urls(channel, max_videos=10):
        info = dl.get_video_info(candidate_url)
        if info:
            video_url = candidate_url
            break

    if not video_url:
        print("ERROR: No playable videos found for channel", channel)
        sys.exit(2)

    print("Found video:", video_url)

    shorts = str(settings.max_shorts_per_video)
    cmd = [
        sys.executable,
        "cli.py",
        "process",
        "--url",
        video_url,
        "--shorts",
        shorts,
        "--no-upload",
    ]
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print("Return code:", proc.returncode)
    print(proc.stdout)
    print(proc.stderr)
    if proc.returncode != 0:
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
