#!/usr/bin/env python3
"""Trim a clip dir to [start, end] seconds: raw.mp4, short.mp4 and captions.ass (times shifted).

    python3 trim.py <clip_dir> <start> <end>
Keeps originals as *.full.* the first time.
"""
import re, shutil, subprocess, sys
from pathlib import Path

d, s, e = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
for name in ("raw.mp4", "short.mp4"):
    src = d / name
    full = d / name.replace(".mp4", ".full.mp4")
    if not full.exists():
        shutil.copy2(src, full)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s}", "-to", f"{e}", "-i", str(full),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(src)], check=True)

ass = d / "captions.ass"
if ass.exists():
    full = d / "captions.full.ass"
    if not full.exists():
        shutil.copy2(ass, full)

    def t2s(t):
        h, m, x = t.split(":"); return int(h) * 3600 + int(m) * 60 + float(x)

    def s2t(x):
        x = max(0.0, x); h = int(x // 3600); m = int(x % 3600 // 60); return f"{h}:{m:02d}:{x % 60:05.2f}"

    out = []
    for line in full.read_text(encoding="utf-8", errors="replace").splitlines():
        mm = re.match(r"(Dialogue: \d+,)([^,]+),([^,]+),(.*)", line)
        if not mm:
            out.append(line); continue
        a, b = t2s(mm.group(2)) - s, t2s(mm.group(3)) - s
        if b <= 0 or a >= e - s or b - a <= 0.01:
            continue
        out.append(f"{mm.group(1)}{s2t(a)},{s2t(min(b, e - s))},{mm.group(4)}")
    ass.write_text("\n".join(out) + "\n")
print(f"TRIMMED {d.name} {s}-{e} ({e - s:.1f}s)")
