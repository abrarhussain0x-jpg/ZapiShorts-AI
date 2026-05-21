import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.config.settings import settings
from src.services.video_editor import VideoEditor

video_path = Path(
    r"c:\Users\AbrarHussainBhat\Downloads\ZapiShorts-AI-main\data\downloads\eMRRwgkMc2E_Girl Gets Trapped in a Room Where the Temperature Goes up 1 Degree Every Second.mp4"
)
output_dir = Path(settings.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)

settings.scene_detection_enabled = False
editor = VideoEditor()
segments = editor.extract_short_segments(
    str(video_path), short_duration=45, num_segments=3, selection_mode="easy_best"
)
print(f"segments={segments}")

rendered = []
for index, (start_time, end_time) in enumerate(segments[:3], start=1):
    output_path = output_dir / f"{video_path.stem}__short_{index:02d}.mp4"
    success = editor.create_short(
        str(video_path),
        str(output_path),
        start_time=start_time,
        duration=min(45, max(1, int(end_time - start_time))),
        add_captions=False,
    )
    print(f"render {index}={success} path={output_path}")
    if success:
        rendered.append(str(output_path))

print(f"rendered={rendered}")
