#!/usr/bin/env python3
"""Live stream clipper (Twitch + YouTube Live): record -> watch chat -> cut on
hype -> caption -> (upload).

Stdlib only. External tools: streamlink, ffmpeg, whisper-cli (whisper.cpp),
yt-dlp (YouTube chat only).

    python3 clipper.py <twitch-channel | twitch URL | youtube live URL> [--upload] ...

Output layout (under --out, default ./clips-<channel>):
    buffer/seg_00042.ts   rolling 10s recording segments (old ones deleted)
    buffer/segments.csv   ffmpeg segment list (filename,start,end)
    chat.jsonl            every chat message, wall-clock stamped
    clips/<id>/           raw.mp4, short.mp4, captions.srt/.ass, meta.json
    CLIP_NOW              touch this file to force a clip right now
    events.log            one line per spike/clip/upload
"""
import argparse, collections, csv, json, os, re, shutil, signal, socket
import subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HYPE = re.compile(
    r"\b(lul|lmao+|lol+|kekw|omegalul|pog+|poggers|pogchamp|w+|l+|clip+ ?(it|that)?|"
    r"no way|holy|wtf|omg|bro+|ayo+|monkas|pepelaugh|icant|gg+|\?{2,}|!{2,})\b",
    re.I)

CHILDREN = []          # every subprocess we spawn, killed on exit

def ytdlp_cookie_args(a):
    return ["--cookies", str(a.cookies)] if getattr(a, "cookies", None) else []


def streamlink_cookie_args(a):
    if not getattr(a, "cookies", None):
        return []
    out = []
    for line in Path(a.cookies).read_text().splitlines():
        f = line.split("\t")
        if len(f) == 7 and not line.startswith("#") and f[0].endswith("youtube.com"):
            out += ["--http-cookie", f"{f[5]}={f[6]}"]
    return out


def shutdown(code=0):
    for c in CHILDREN:
        try: c.kill()
        except Exception: pass
    os._exit(code)

def log(out, msg):
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(out / "events.log", "a") as f:
        f.write(line + "\n")

# ---------------------------------------------------------------- recorder
class Recorder:
    """streamlink | ffmpeg segment muxer. Maps segments to wall-clock time."""

    def __init__(self, a, out):
        self.a, self.buf = a, out / "buffer"
        self.buf.mkdir(parents=True, exist_ok=True)
        for f in self.buf.glob("r*"):            # stale segments from earlier runs
            f.unlink(missing_ok=True)
        self.segs = []          # (path, wall_start, wall_end)
        self.seen = set()
        self.lock = threading.Lock()
        self.live = False
        self.procs = []
        self.run_id = 0
        self.ended = False

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._index, daemon=True).start()

    def _loop(self):
        a = self.a
        while True:
            self.run_id += 1
            pre = f"r{int(time.time())}_{self.run_id:03d}_"
            if a.platform == "youtube" and getattr(a, "cookies", None):
                # streamlink can't pass YouTube's bot check; yt-dlp + cookies can
                cmd = ["yt-dlp", *ytdlp_cookie_args(a), "-f", "best[height<=1080]/best",
                       "--no-part", "--quiet", "-o", "-", a.url]
            else:
                cmd = ["streamlink", "--twitch-disable-ads", "--twitch-low-latency",
                       "--retry-streams", "15", "--retry-max", "0", "--stdout",
                       *streamlink_cookie_args(a), a.url, a.quality]
            sl = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  start_new_session=True)   # own group: watchdog kills yt-dlp's ffmpeg too
            ff = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                 "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
                 "-f", "segment", "-segment_time", "10",
                 "-segment_list", str(self.buf / f"{pre}segments.csv"),
                 "-segment_list_type", "csv", "-reset_timestamps", "1",
                 str(self.buf / f"{pre}seg_%05d.ts")],
                stdin=sl.stdout, stderr=subprocess.DEVNULL)
            sl.stdout.close()
            self.procs = [sl, ff]
            CHILDREN.extend(self.procs)
            # watchdog: a hung download keeps both processes alive but writes nothing
            last, t_start = time.time(), time.time()
            while ff.poll() is None:
                time.sleep(10)
                segs = list(self.buf.glob(f"{pre}seg_*.ts"))
                newest = max((f.stat().st_mtime for f in segs), default=0)
                if newest: last = max(last, newest)
                if time.time() - last > 90:
                    log(a.outdir, "recorder stalled (no new segment for 90s) - restarting it")
                    for proc in (sl, ff):
                        try: os.killpg(proc.pid, signal.SIGKILL) if proc is sl else proc.kill()
                        except Exception: pass
                    break
            try: ff.wait(timeout=10); sl.wait(timeout=10)
            except subprocess.TimeoutExpired: pass
            self.live = False
            log(self.a.outdir, "stream offline / recorder exited - waiting for it to go live again")
            if a.exit_when_ended and a.platform == "youtube":
                st = subprocess.run(["yt-dlp", *ytdlp_cookie_args(a), "--print", "live_status", a.url],
                                    capture_output=True, text=True).stdout.strip()
                if st and st != "is_live":
                    log(a.outdir, f"live ended (live_status={st}) - finishing queued clips then exiting")
                    self.ended = True
            time.sleep(5)

    def _index(self):
        """Poll ffmpeg's segment list. A row appears the moment a segment is
        closed, so 'now' is that segment's wall-clock END."""
        while True:
            for lst in sorted(self.buf.glob("r*_segments.csv")):
                try:
                    rows = list(csv.reader(open(lst)))
                except OSError:
                    continue
                for row in rows:
                    if len(row) < 3 or (lst.name, row[0]) in self.seen:
                        continue
                    self.seen.add((lst.name, row[0]))
                    dur = float(row[2]) - float(row[1])
                    now = time.time()
                    with self.lock:
                        self.segs.append((self.buf / row[0], now - dur, now))
                    if not self.live:
                        self.live = True
                        log(self.a.outdir, f"LIVE - recording {self.a.channel}")
            self._prune()
            time.sleep(0.5)

    def _prune(self):
        cutoff = time.time() - self.a.keep_minutes * 60
        with self.lock:
            keep = []
            for s in self.segs:
                if s[2] < cutoff:
                    s[0].unlink(missing_ok=True)
                else:
                    keep.append(s)
            self.segs = keep

    def covered_until(self):
        with self.lock:
            return self.segs[-1][2] if self.segs else 0

    def cut(self, t0, t1, dest):
        """Concat the segments overlapping [t0,t1] and trim to exactly that."""
        with self.lock:
            parts = [s for s in self.segs if s[2] > t0 and s[1] < t1]
        if not parts:
            return False
        lst = dest.with_suffix(".txt")
        lst.write_text("".join(f"file '{p[0]}'\n" for p in parts))
        offset = max(0.0, t0 - parts[0][1])
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "concat", "-safe", "0", "-i", str(lst),
             "-ss", f"{offset:.2f}", "-t", f"{t1 - t0:.2f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-c:a", "aac", "-b:a", "160k", str(dest)])
        lst.unlink(missing_ok=True)
        return r.returncode == 0 and dest.exists()

    def stop(self):
        for p in self.procs:
            try: p.terminate()
            except Exception: pass

# ---------------------------------------------------------------- chat
class Chat:
    """Anonymous Twitch IRC reader (justinfan = read-only, no login)."""

    def __init__(self, a, out):
        self.a, self.out = a, out
        self.msgs = collections.deque()   # (ts, user, text)
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self._session()
            except Exception as e:
                log(self.out, f"chat reconnect ({e})")
            time.sleep(3)

    def _session(self):
        if self.a.platform == "youtube":
            return self._youtube()
        s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=300)
        nick = f"justinfan{int(time.time()) % 100000}"
        s.sendall(f"PASS SCHMOOPIIE\r\nNICK {nick}\r\nJOIN #{self.a.channel.lower()}\r\n".encode())
        f = s.makefile("r", encoding="utf-8", errors="replace")
        log_f = open(self.out / "chat.jsonl", "a")
        for line in f:
            if line.startswith("PING"):
                s.sendall(b"PONG :tmi.twitch.tv\r\n"); continue
            m = re.match(r":(\w+)!\S+ PRIVMSG #\S+ :(.*)", line.rstrip("\r\n"))
            if not m:
                continue
            now = time.time()
            with self.lock:
                self.msgs.append((now, m[1], m[2]))
                while self.msgs and self.msgs[0][0] < now - 600:
                    self.msgs.popleft()
            log_f.write(json.dumps({"t": now, "u": m[1], "m": m[2]}) + "\n")
            log_f.flush()

    def _youtube(self):
        """yt-dlp follows YouTube live chat as JSON lines (~5s batches).
        Messages carry their own send time (timestampUsec), so batching
        doesn't smear the spike."""
        base = self.out / "ytchat"
        for f in self.out.glob("ytchat*"):
            f.unlink(missing_ok=True)
        proc = subprocess.Popen(["yt-dlp", *ytdlp_cookie_args(self.a), "--skip-download", "--write-subs",
                                 "--sub-langs", "live_chat", "-o", str(base), self.a.url],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        CHILDREN.append(proc)
        part = Path(str(base) + ".live_chat.json.part")
        log_f = open(self.out / "chat.jsonl", "a")
        pos = 0
        try:
            while proc.poll() is None:
                time.sleep(1)
                if not part.exists():
                    continue
                with open(part, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    data = f.read()
                cut = data.rfind("\n") + 1          # only complete lines
                pos += len(data[:cut].encode("utf-8"))
                for line in data[:cut].splitlines():
                    try:
                        acts = json.loads(line)["replayChatItemAction"]["actions"]
                    except (ValueError, KeyError):
                        continue
                    for act in acts:
                        it = act.get("addChatItemAction", {}).get("item", {}) \
                                .get("liveChatTextMessageRenderer")
                        if not it:
                            continue
                        ts = int(it.get("timestampUsec", time.time() * 1e6)) / 1e6
                        user = it.get("authorName", {}).get("simpleText", "?")
                        text = "".join(r.get("text") or (r.get("emoji", {}).get("shortcuts") or [""])[0]
                                       for r in it.get("message", {}).get("runs", []))
                        with self.lock:
                            self.msgs.append((ts, user, text))
                            while self.msgs and self.msgs[0][0] < time.time() - 600:
                                self.msgs.popleft()
                        log_f.write(json.dumps({"t": ts, "u": user, "m": text}) + "\n")
                log_f.flush()
        finally:
            proc.kill()
        raise RuntimeError("yt-dlp chat follower exited")

    def window(self, t0, t1):
        with self.lock:
            return [x for x in self.msgs if t0 <= x[0] < t1]

    def score(self, t0, t1):
        """Unique chatters (spam-proof) + bonus for hype messages."""
        w = self.window(t0, t1)
        users = {u for _, u, _ in w}
        hype = sum(1 for _, _, m in w if HYPE.search(m))
        return len(users) + 0.5 * hype, w

# ---------------------------------------------------------------- detector
def detect(a, chat, rec, on_spike):
    """Spike = last W seconds score >= mult x baseline AND >= floor."""
    W = a.window
    last = 0
    manual = a.outdir / "CLIP_NOW"
    warm_until = None          # need a real baseline before judging spikes
    while True:
        time.sleep(1)
        now = time.time()
        if manual.exists():
            manual.unlink(missing_ok=True)
            log(a.outdir, "manual CLIP_NOW trigger")
            on_spike(now - a.chat_delay, 0, 0, chat.window(now - W, now)); last = now; continue
        if rec.ended:
            log(a.outdir, "waiting 240s for in-flight clips/uploads, then exiting")
            time.sleep(240); log(a.outdir, "DONE - live ended"); shutdown(0)
        if not rec.live or now - last < a.cooldown:
            continue
        if warm_until is None:
            warm_until = now + max(a.warmup, a.pre)
            log(a.outdir, f"warming up {warm_until - now:.0f}s (building chat baseline)")
        if now < warm_until:
            continue
        now -= a.chat_delay                    # YouTube chat arrives in batches
        cur, msgs = chat.score(now - W, now)
        # baseline = median score of W-sized windows over the previous 3 min
        base = sorted(chat.score(now - k * W - W, now - k * W)[0]
                      for k in range(2, int(180 / W)))
        baseline = base[len(base) // 2] if base else 0
        if cur >= a.floor and cur >= a.mult * max(baseline, 1):
            last = now + a.chat_delay
            on_spike(now, cur, baseline, msgs)

# ---------------------------------------------------------------- render
def srt_to_ass(srt, ass, accent):
    blocks = re.split(r"\n\s*\n", srt.read_text(encoding="utf-8", errors="replace").strip())
    ev = []
    for b in blocks:
        lines = b.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\S+) --> (\S+)", lines[1])
        if not m:
            continue
        txt = " ".join(lines[2:]).strip()
        if not txt or re.fullmatch(r"[\[\(].*[\]\)]", txt):   # drop [Music] etc
            continue
        conv = lambda t: (lambda h, mi, s: f"{int(h)}:{mi}:{s.replace(',', '.')[:-1]}")(*t.split(":"))
        ev.append(f"Dialogue: 0,{conv(m[1])},{conv(m[2])},Cap,,0,0,0,,"
                  "{\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)}" + txt.upper())
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,92,{accent},&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,7,3,2,70,70,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n")
    return len(ev)

def vertical_filter(a):
    if a.layout == "crop":
        return "[0:v]scale=-2:1920,crop=1080:1920[v]"
    if a.layout == "split":           # facecam on top, gameplay below
        x, y, w, h = a.cam.split(":")
        return (f"[0:v]split[c][g];[c]crop={w}:{h}:{x}:{y},scale=1080:640:force_original_aspect_ratio=increase,crop=1080:640[top];"
                "[g]scale=-2:1280,crop=1080:1280[bot];[top][bot]vstack[v]")
    return ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,scale=270:480,boxblur=12:2,eq=brightness=-0.08,scale=1080:1920[bg];"
            "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")

def render(a, raw, d):
    wav = d / "audio.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True)
    caps = 0
    if not a.no_captions and Path(a.model).exists():
        subprocess.run(["whisper-cli", "-m", a.model, "-f", str(wav), "-l", a.lang,
                        "-osrt", "-ml", "18", "-sow", "-np", "-of", str(d / "captions")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if (d / "captions.srt").exists():
            caps = srt_to_ass(d / "captions.srt", d / "captions.ass", a.accent)
    vf = vertical_filter(a)
    if caps:
        vf += f";[v]ass='{d / 'captions.ass'}'[v2]"
        out_label = "[v2]"
    else:
        out_label = "[v]"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                    "-filter_complex", vf, "-map", out_label, "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(d / "short.mp4")], check=True)
    wav.unlink(missing_ok=True)
    text = ""
    if (d / "captions.srt").exists():
        text = " ".join(" ".join(l.split()) for l in (d / "captions.srt").read_text(encoding="utf-8", errors="replace").splitlines()
                        if l and not l[0].isdigit()).strip()
    return text

def make_title(a, transcript, msgs):
    words = collections.Counter(w for _, _, m in msgs for w in m.split() if len(w) > 1)
    emote = words.most_common(1)[0][0] if words else ""
    hook = transcript[:60].rsplit(" ", 1)[0] if len(transcript) > 60 else transcript
    base = f'{a.channel}: "{hook}"' if hook else f"{a.channel} chat went {emote}"
    return (base[:88] + " #Shorts").strip()

# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="twitch channel name, twitch URL, or YouTube live URL")
    p.add_argument("--name", help="label used for folders/titles (default: channel name)")
    p.add_argument("--out", help="output dir (default ./clips-<channel>)")
    p.add_argument("--quality", default="1080p60,1080p,720p60,720p,best")
    p.add_argument("--pre", type=float, default=22, help="seconds before spike (chat lags the moment)")
    p.add_argument("--post", type=float, default=8, help="seconds after spike")
    p.add_argument("--window", type=int, default=5, help="chat scoring window, seconds")
    p.add_argument("--mult", type=float, help="spike = score >= mult x baseline (default 3 Twitch, 2 YouTube)")
    p.add_argument("--floor", type=float, help="minimum score to count as a spike (default 12 Twitch, 6 YouTube)")
    p.add_argument("--chat-delay", type=float, help="score chat this many s in the past (default 0 Twitch, 10 YouTube)")
    p.add_argument("--export", help="also copy every finished short.mp4 into this folder")
    p.add_argument("--cooldown", type=float, default=45)
    p.add_argument("--warmup", type=float, default=90, help="seconds of chat to learn the baseline before clipping")
    p.add_argument("--keep-minutes", type=float, default=30, help="recording buffer to keep on disk")
    p.add_argument("--layout", choices=["blur", "crop", "split"], default="blur")
    p.add_argument("--cam", default="0:0:480:270", help="split layout facecam x:y:w:h in source px")
    p.add_argument("--model", default=os.path.expanduser("~/.cache/whisper/ggml-small.bin"))
    p.add_argument("--lang", default="auto")
    p.add_argument("--accent", default="&H0000FFFF", help="caption colour, ASS &HAABBGGRR (default yellow)")
    p.add_argument("--no-captions", action="store_true")
    p.add_argument("--failed-dir", default="output", help="where shorts that fail to upload are saved")
    p.add_argument("--exit-when-ended", action="store_true", help="exit once the YouTube live has ended")
    p.add_argument("--upload", action="store_true", help="upload each short to YouTube as soon as it renders")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    p.add_argument("--max-clips", type=int, default=0, help="stop after N clips (0 = unlimited)")
    a = p.parse_args()
    src = a.source.strip()
    if re.search(r"(youtube\.com|youtu\.be)/", src):
        a.platform, a.url = "youtube", src
        if not a.name:
            r = subprocess.run(["yt-dlp", "--print", "%(channel)s", "--no-warnings", src],
                               capture_output=True, text=True)
            a.name = r.stdout.strip().splitlines()[0] if r.stdout.strip() else "youtube"
    else:
        a.platform = "twitch"
        login = re.sub(r"^(https?://)?(www\.)?twitch\.tv/", "", src).strip("/").split("/")[0]
        a.url = f"https://twitch.tv/{login}"
        a.name = a.name or login
    a.channel = re.sub(r"[^A-Za-z0-9_-]+", "", a.name) or "stream"
    yt = a.platform == "youtube"
    a.mult = a.mult if a.mult is not None else (2.0 if yt else 3.0)
    a.floor = a.floor if a.floor is not None else (6 if yt else 12)
    a.chat_delay = a.chat_delay if a.chat_delay is not None else (10 if yt else 0)
    a.outdir = Path(a.out or f"clips-{a.channel.lower()}").resolve()
    (a.outdir / "clips").mkdir(parents=True, exist_ok=True)
    pidf = a.outdir / "clipper.pid"                 # one clipper per folder
    if pidf.exists():
        try:
            os.kill(int(pidf.read_text()), 0)
            sys.exit(f"another clipper (pid {pidf.read_text().strip()}) is using {a.outdir} - stop it or use --out")
        except (ProcessLookupError, ValueError):
            pass
    pidf.write_text(str(os.getpid()))
    # YouTube bot-check: optional cookies (per-process private copy; yt-dlp rewrites its jar)
    a.cookies = None
    src = Path(os.environ.get("LIVE_CLIPPER_COOKIES", Path.home() / ".config/live-clipper/yt-cookies.txt"))
    if a.platform == "youtube" and src.exists():
        a.cookies = a.outdir / ".cookies.txt"
        shutil.copy2(src, a.cookies); os.chmod(a.cookies, 0o600)

    for tool in ("streamlink", "ffmpeg") + (("yt-dlp",) if yt else ()):
        if not shutil.which(tool):
            sys.exit(f"missing {tool} - run: bash {HERE}/setup.sh")
    if not a.no_captions and not (shutil.which("whisper-cli") and Path(a.model).exists()):
        print(f"! captions disabled: need whisper-cli + {a.model} (run setup.sh)")
        a.no_captions = True

    rec, chat = Recorder(a, a.outdir), Chat(a, a.outdir)
    rec.start(); chat.start()
    log(a.outdir, f"watching {a.url} ({a.platform}) -> {a.outdir}  (upload={'on' if a.upload else 'off'})")
    count = [0]
    q = []
    qlock = threading.Condition()

    def on_spike(t, score, base, msgs):
        log(a.outdir, f"SPIKE score={score:.0f} baseline={base:.0f} msgs={len(msgs)}")
        with qlock:
            q.append((t, msgs)); qlock.notify()

    def worker():
        while True:
            with qlock:
                while not q: qlock.wait()
                t, msgs = q.pop(0)
            t0, t1 = t - a.pre, t + a.post
            while rec.covered_until() < t1 + 1:      # wait for post-roll to be recorded
                if time.time() > t1 + 60: break
                time.sleep(1)
            cid = datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S")
            d = a.outdir / "clips" / cid; d.mkdir(exist_ok=True)
            if not rec.cut(t0, t1, d / "raw.mp4"):
                log(a.outdir, f"clip {cid}: no recording for that window (stream just started?)"); continue
            try:
                transcript = render(a, d / "raw.mp4", d)
            except Exception as e:                   # never let one bad clip kill the worker thread
                log(a.outdir, f"clip {cid}: render failed {e!r}"); continue
            title = make_title(a, transcript, msgs)
            top = collections.Counter(m for _, _, m in msgs).most_common(8)
            meta = {"id": cid, "channel": a.channel, "spike_time": t, "title": title,
                    "transcript": transcript, "top_chat": top,
                    "description": f"Clipped live from {a.url}\n\n#Shorts #{a.channel}",
                    "file": str(d / "short.mp4"), "uploaded": None}
            (d / "meta.json").write_text(json.dumps(meta, indent=2))
            log(a.outdir, f"CLIP READY {d / 'short.mp4'}  title={title!r}")
            if a.export:
                ex = Path(a.export).expanduser(); ex.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / "short.mp4", ex / f"{a.channel}-{cid}.mp4")
                log(a.outdir, f"exported -> {ex / f'{a.channel}-{cid}.mp4'}")
            if a.upload:
                r = subprocess.run(["uv", "run", "--quiet", str(HERE / "upload_short.py"),
                                    "--meta", str(d / "meta.json"), "--privacy", a.privacy],
                                   capture_output=True, text=True)
                log(a.outdir, f"UPLOAD {cid}: {(r.stdout or r.stderr).strip().splitlines()[-1:]}")
                if r.returncode != 0 or "UPLOADED" not in (r.stdout or ""):
                    fo = Path(a.failed_dir).expanduser(); fo.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(d / "short.mp4", fo / f"{a.channel}-{cid}.mp4")
                    shutil.copy2(d / "meta.json", fo / f"{a.channel}-{cid}.meta.json")
                    log(a.outdir, f"UPLOAD FAILED {cid} -> saved to {fo}")
            count[0] += 1
            if a.max_clips and count[0] >= a.max_clips:
                log(a.outdir, "max clips reached - exiting"); shutdown(0)

    threading.Thread(target=worker, daemon=True).start()
    signal.signal(signal.SIGINT, lambda *_: shutdown(0))
    signal.signal(signal.SIGTERM, lambda *_: shutdown(0))
    detect(a, chat, rec, on_spike)

if __name__ == "__main__":
    main()
