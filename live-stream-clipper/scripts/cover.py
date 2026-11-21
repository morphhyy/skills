#!/usr/bin/env python3
"""Make a viral cover for a vertical Short and burn it into the opening seconds.

    python3 cover.py <clip_dir> --hook "SPEED BOUGHT A $900K CHAIN" [--label "SPEED x GTA 6"] [--at 12]

Writes <clip_dir>/cover.jpg (thumbnail) and <clip_dir>/final.mp4 (short.mp4 with
the hook text + LIVE badge over the first --hold seconds; the rest untouched).
"""
import argparse, subprocess, tempfile, textwrap
from pathlib import Path

ANTON = str(Path.home() / "Library/Fonts/Anton-Regular.ttf")
if not Path(ANTON).exists():
    ANTON = "/Library/Fonts/Anton-Regular.ttf"
if not Path(ANTON).exists():
    ANTON = "/System/Library/Fonts/Supplemental/Impact.ttf"


# words masked in burned-in captions (slurs removed entirely, swears starred)
SLURS = [r"n+i+g+g+(?:a|er|uh|as|ers|az)\w*", r"f+a+g+(?:got|gots|s)?", r"r+e+t+a+r+d+(?:s|ed)?", r"tr+a+nn+(?:y|ies)"]
SWEARS = {r"f+u+c+k": "F*CK", r"s+h+i+t": "SH*T", r"b+i+t+c+h": "B*TCH", r"d+i+c+k": "D*CK",
          r"p+u+s+s+y": "P*SSY", r"c+u+n+t": "C*NT", r"a+s+s+h+o+l+e": "A**HOLE"}


def clean_caption(text):
    import re as _re
    for pat in SLURS:
        text = _re.sub(r"\b" + pat + r"\b", "", text, flags=_re.I)
    for pat, rep in SWEARS.items():   # no leading \b: also catches compounds like "motherfucking"
        text = _re.sub(r"(\w*?)" + pat, lambda m: m.group(1) + rep, text, flags=_re.I)
    return _re.sub(r"\s{2,}", " ", text)


def esc(p):
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def filters(tmp, hook, label, enable=""):
    hook = "".join(ch for ch in hook if ord(ch) < 0x2000).strip()   # font has no emoji
    lines = textwrap.wrap(hook.upper(), 15)[:4]
    fs = 140 if len(lines) <= 2 else 110
    f = []
    # LIVE badge (top-left of the upper blur area)
    f.append(f"drawbox=x=60:y=120:w=250:h=100:color=0xE50914@1:t=fill{enable}")
    f.append(f"drawbox=x=88:y=158:w=26:h=26:color=white@1:t=fill{enable}")
    (tmp / "live.txt").write_text("LIVE")
    f.append(f"drawtext=fontfile='{esc(ANTON)}':textfile='{esc(tmp / 'live.txt')}':fontsize=72:"
             f"fontcolor=white:x=130:y=120+(100-th)/2{enable}")
    # channel / game label
    (tmp / "label.txt").write_text(label.upper())
    f.append(f"drawtext=fontfile='{esc(ANTON)}':textfile='{esc(tmp / 'label.txt')}':fontsize=80:"
             f"fontcolor=white:borderw=6:bordercolor=black:x=w-tw-60:y=125{enable}")
    # hook text, centred in the upper blurred band (y 260..640)
    total = len(lines) * (fs + 10)
    y0 = 260 + max(0, (390 - total) // 2)
    for i, ln in enumerate(lines):
        t = tmp / f"h{i}.txt"; t.write_text(ln)
        color = "0xFFE600" if i % 2 == 0 else "white"
        f.append(f"drawtext=fontfile='{esc(ANTON)}':textfile='{esc(t)}':fontsize={fs}:"
                 f"fontcolor={color}:borderw=10:bordercolor=black:x=(w-tw)/2:y={y0 + i * (fs + 10)}{enable}")
    return ",".join(f)


def blur(rw, cut=""):
    # [0:v] -> [b] (16:9 for the layout) + [rawcam] (untouched source for a sharp facecam crop)
    # cut: optional crop on the gameplay that zooms past the streamer's own facecam overlay
    return ("[0:v]split=3[a][b][rawcam];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,scale=270:480,boxblur=12:2,eq=brightness=-0.08,scale=1080:1920[bg0];"
            f"[b]{cut}scale=1080:-2:flags=lanczos[fg];[bg0][fg]overlay=(W-w)/2:(H-h)/2[base];")


def cam_cut(sx, sw, rw, rh, margin=40):
    """Crop (same aspect) that excludes a facecam sitting on the left or right edge of the source."""
    if sx + sw / 2 < rw / 2:                       # cam on the left: keep everything right of it
        cx = min(rw - 2, sx + sw + margin); cw = rw - cx
    else:                                          # cam on the right: keep everything left of it
        cx = 0; cw = max(2, sx - margin)
    cw -= cw % 2
    ch = round(cw * rh / rw / 2) * 2
    return f"crop={cw}:{ch}:{cx}:{(rh - ch) // 2},"


def graph(tmp, a, enable="", raw=False, ass=None, rawsize=None):
    x, y, w, h = map(int, a.cam.split(":"))           # in short.mp4 (1080x1920) pixels
    W = 960; H = round(W * h / w / 2) * 2
    caps = f"ass='{esc(ass)}'," if ass else ""
    up = f"scale={W}:{H}:flags=lanczos,unsharp=5:5:0.8:5:5:0.0"
    if raw and rawsize:
        rw, rh = rawsize                               # map to source pixels
        k = rw / 1080; top = (1920 - 1080 * rh / rw) / 2
        sx, sy, sw, sh = round(x * k), round((y - top) * k), round(w * k), round(h * k)
        cut = cam_cut(sx, sw, rw, rh) if a.hide_cam else ""
        head = blur(rw, cut) + f"[rawcam]crop={sw}:{sh}:{max(0, sx)}:{max(0, sy)},{up}"
        bg = "[base]"
    else:
        head = f"[0:v]split[bg0][c];[c]crop={w}:{h}:{x}:{y},{up}"
        bg = "[bg0]"
    cam = (head + f",pad={W+16}:{H+16}:8:8:color=0xFFE600[cam];"
           f"{bg}[cam]overlay=(W-w)/2:{1290 + max(0, (590 - H) // 2)}[v0];")
    return cam + "[v0]" + caps + filters(tmp, a.hook, a.label, enable) + "[v]"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("clip_dir")
    p.add_argument("--hook", required=True)
    p.add_argument("--label", default="SPEED x GTA 6")
    p.add_argument("--at", type=float, default=10, help="second of the short to use for the cover frame")
    p.add_argument("--cam", default="2:916:216:136", help="facecam x:y:w:h in short.mp4 px (blur layout); 'none' to skip")
    p.add_argument("--keep-cam", dest="hide_cam", action="store_false",
                   help="don't crop the streamer's facecam out of the gameplay (default: crop it)")
    p.add_argument("--cover-only", action="store_true", help="only write cover.jpg")
    p.add_argument("--hold", type=float, default=9999, help="seconds the cover text stays on the video")
    a = p.parse_args()
    d = Path(a.clip_dir)
    src = d / "short.mp4"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        g = (lambda en="": graph(tmp, a, en)) if a.cam != "none" else \
            (lambda en="": "[0:v]" + filters(tmp, a.hook, a.label, en) + "[v]")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.at), "-i", str(src), "-frames:v", "1",
                        "-filter_complex", g(), "-map", "[v]", "-q:v", "2", str(d / "cover.jpg")], check=True)
        if a.cover_only:
            print(f"OK {d / 'cover.jpg'}"); return
        en = f":enable='lt(t\\,{a.hold})'"
        vin, vg = src, g(en)
        if a.cam != "none" and (d / "raw.mp4").exists():
            # rebuild from raw so captions sit above the facecam box instead of under it
            ass = None
            if (d / "captions.ass").exists():
                ass = tmp / "caps.ass"
                lines = []
                for ln in (d / "captions.ass").read_text(encoding="utf-8", errors="replace").replace(",70,70,560,1", ",70,70,690,1").splitlines():
                    if ln.startswith("Dialogue:"):
                        head, _, txt = ln.rpartition("}") if "}" in ln else ln.rpartition(",,")
                        ln = head + ("}" if "}" in ln else ",,") + clean_caption(txt)
                    lines.append(ln)
                ass.write_text("\n".join(lines) + "\n")
            wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                 "stream=width,height", "-of", "csv=p=0", str(d / "raw.mp4")],
                                capture_output=True, text=True).stdout.strip().split(",")
            vin, vg = d / "raw.mp4", graph(tmp, a, en, raw=True, ass=ass, rawsize=(int(wh[0]), int(wh[1])))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(vin),
                        "-filter_complex", vg, "-map", "[v]", "-map", "0:a?",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", "-movflags", "+faststart", str(d / "final.mp4")], check=True)
        # thumbnail = the finished video's frame (correct captions/cover/cam)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a.at), "-i", str(d / "final.mp4"),
                        "-frames:v", "1", "-q:v", "2", str(d / "cover.jpg")], check=True)
    print(f"OK {d / 'cover.jpg'} {d / 'final.mp4'}")


if __name__ == "__main__":
    main()
