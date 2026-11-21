# skills

Skills for [Claude Code](https://claude.com/claude-code). Each folder is one skill: a `SKILL.md` that tells Claude when and how to use it, plus any scripts it runs.

| Skill | What it does |
|---|---|
| [live-stream-clipper](live-stream-clipper/SKILL.md) | Clips Twitch and YouTube streams **while they're live**. Watches chat for hype spikes, cuts the moment, burns in captions, renders a 1080×1920 Short, and can upload it to YouTube. |

## Install a skill

```bash
git clone https://github.com/morphhyy/skills.git
cp -r skills/live-stream-clipper ~/.claude/skills/                 # every project
# or
cp -r skills/live-stream-clipper <your-project>/.claude/skills/    # one project
```

Restart Claude Code. The skill loads on its own when you ask for something it covers, for example *"clip xQc's stream live and give me 3 shorts"*.

---

## live-stream-clipper

```
streamlink / yt-dlp ──► ffmpeg 10s segment buffer
Twitch IRC / YouTube live chat ──► spike detector ──► cut [spike-22s, spike+8s]
   ──► whisper.cpp captions ──► vertical Short ──► (optional) YouTube upload
```

Everything is free. Chat is read anonymously. Only the YouTube upload needs a Google account.

### Requirements

| Tool | Used for |
|---|---|
| Python 3.10+ | the clipper (standard library only) |
| [ffmpeg](https://ffmpeg.org) with libass and freetype | recording, cutting, captions, covers |
| [streamlink](https://streamlink.github.io) | Twitch recording |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube recording and live chat |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (`whisper-cli`) + a model | captions (optional: use `--no-captions`) |
| [uv](https://docs.astral.sh/uv/) | YouTube uploader (pulls its own Google API packages) |

**macOS**

```bash
brew install python ffmpeg streamlink yt-dlp whisper-cpp uv
```

**Debian / Ubuntu**

```bash
sudo apt install python3 ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install streamlink && uv tool install yt-dlp
# whisper-cli: build from source (https://github.com/ggml-org/whisper.cpp#quick-start)
```

**Whisper model** (about 466 MB; use `base` for a smaller and faster model)

```bash
mkdir -p ~/.cache/whisper
curl -L -o ~/.cache/whisper/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

> Tested on macOS. Linux should work. Windows isn't supported yet: the recorder's process handling and the helper `.sh` scripts assume a POSIX system, so use WSL.

### Usage

Run these from your project folder. Clips are saved there.

```bash
S=~/.claude/skills/live-stream-clipper/scripts

python3 $S/clipper.py xqc                                          # Twitch channel
python3 $S/clipper.py "https://www.youtube.com/watch?v=VIDEO_ID"   # YouTube live
python3 $S/clipper.py xqc --max-clips 3 --export output            # stop after 3, copy to ./output
python3 $S/clipper.py xqc --layout split --cam 0:0:480:270          # facecam on top, gameplay below
python3 $S/clipper.py xqc --upload --privacy private                # upload every Short
```

It waits for the stream to go live, learns the normal chat speed for 90 seconds, then clips when chat spikes. It survives stream drops and keeps only the last 30 minutes of recording on disk.

- **Watch progress:** `tail -f clips-xqc/events.log`
- **Force a clip now:** `touch clips-xqc/CLIP_NOW`
- **Stop:** Ctrl+C

Output:

```
clips-<channel>/
  events.log         LIVE / SPIKE / CLIP READY / UPLOAD
  chat.jsonl         every chat message with timestamps
  clips/<id>/        raw.mp4  short.mp4  captions.srt  meta.json
```

**Layouts:** `blur` (default; the full frame over a blurred background), `crop` (centre crop, good for IRL), `split` (facecam above gameplay; give the facecam box with `--cam x:y:w:h` in source pixels).

### Tuning

| Problem | Try |
|---|---|
| Too many clips | `--mult 4 --floor 40 --cooldown 90` |
| No clips (small chat) | `--mult 2.5 --floor 6` |
| Clip starts too late | raise `--pre` (default 22s) |
| Clip ends too early | raise `--post` (default 8s) |
| Wrong caption language | `--lang en` |
| Captions too slow | use the `base` model with `--model ~/.cache/whisper/ggml-base.bin` |

Run `python3 $S/clipper.py --help` for every option.

### YouTube upload (optional, one time)

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and enable **YouTube Data API v3**.
2. Set up the **OAuth consent screen** as External and add yourself as a test user.
3. Create an **OAuth client ID** of type **Desktop app** and save the JSON as `~/.config/live-clipper/client_secret.json`.
4. Log in once: `uv run $S/upload_short.py --auth`

Upload a single clip by hand:

```bash
uv run $S/upload_short.py --meta clips-xqc/clips/<id>/meta.json --title "your title" --privacy private
```

**Limits:**
- **Private only at first.** Google forces uploads from unaudited API projects to private. Make them public in YouTube Studio, or apply for the API audit.
- **About 6 uploads a day.** Each upload costs about 1,600 of the default 10,000 daily quota units.

### Credentials stay local

The OAuth client, login token and any cookies live in `~/.config/live-clipper/`, never in this repo. The token is written with `0600` permissions. If YouTube blocks the recorder as a bot, export cookies to `~/.config/live-clipper/yt-cookies.txt`. Each run copies them into its own folder, so don't commit or share your `clips-*` folders.

### Use responsibly

These clips come from someone else's stream. Credit the streamer (the default description does), and get their permission or join their clipping program before you upload. Copyright claims and strikes land on **your** channel, and game footage can trigger Content ID.

## License

[MIT](LICENSE)
