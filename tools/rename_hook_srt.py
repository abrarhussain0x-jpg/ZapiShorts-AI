#!/usr/bin/env python3
import re
from pathlib import Path

OUT = Path("data/output")
if not OUT.exists():
    print("No data/output folder found.")
    raise SystemExit(1)

pattern = re.compile(r"__hook_\d{2}\.srt$")

for folder in sorted(p for p in OUT.iterdir() if p.is_dir()):
    srt_files = [p for p in folder.iterdir() if p.is_file() and pattern.search(p.name)]
    if not srt_files:
        continue
    srt_files.sort()
    for i, p in enumerate(srt_files, start=1):
        new_name = folder / f"hook_{i:02d}.srt"
        if new_name.exists():
            print(f"Skipping rename; {new_name} already exists")
            continue
        print(f"Renaming {p} -> {new_name}")
        p.rename(new_name)

print("Done.")
