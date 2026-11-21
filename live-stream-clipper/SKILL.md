---
name: live-stream-clipper
description: Use when the user wants to clip a Twitch or YouTube live stream while it is live (twitch.tv/... or youtube.com/watch?v=... URLs), auto-detect hype moments from chat spikes, turn stream moments into vertical captioned Shorts/TikToks/Reels, or upload clips straight to YouTube Shorts — e.g. launch-night streams (GTA 6), "clip xQc live", "make shorts from this streamer", "auto clipper", streamlink + ffmpeg + whisper pipelines.
---

# Live Stream Clipper → YouTube Shorts

Clips a **Twitch or YouTube** stream **while it is live**: no waiting for the VOD, no downloading hours of footage.

```
streamlink ──► ffmpeg segmenter ──► 10s rolling buffer (wall-clock indexed)
anonymous Twitch IRC / yt-dlp YouTube live chat ──► spike detector ──► cut [spike-22s, spike+8s]
   ──► whisper.cpp captions ──► 1080x1920 Short ──► (optional) YouTube upload
```

Everything is free: streamlink, ffmpeg, whisper.cpp, yt-dlp, and chat read without logging in. Only the YouTube upload needs a Google OAuth client.

## Quick start

```bash
S=.claude/skills/live-stream-clipper/scripts   # run from the project root
bash $S/setup.sh                                  # once: streamlink, ffmpeg, whisper-cpp, uv, model
python3 $S/clipper.py <channel>                   # Twitch: clip to ./clips-<channel>/clips/<id>/short.mp4
python3 $S/clipper.py "https://www.youtube.com/watch?v=ID"   # YouTube live URL
python3 $S/clipper.py <channel> --max-clips 3 --export output   # "give me 3 clips in output/"
python3 $S/clipper.py <channel> --upload          # also upload each Short (private by default)
python3 $S/clipper.py <channel> --upload --privacy public
```

It waits for the channel to go live, learns the chat baseline for 90s (`--warmup`) before auto-clipping, survives stream drops, and keeps only the last 30 min of recording on disk (`--keep-minutes`).

**Run it where the user can watch it.** It is a long-running process. Open it in a visible terminal tab (herdr-app if they use it), not a hidden background job, and say where the clips land.

## Running it for the user: the workflow

1. **Check the stream is live:** `streamlink --json <url> >/dev/null && echo LIVE`. For YouTube, use `yt-dlp --print live_status <url>`. A non-live YouTube video (a VOD) is not this skill's job: the clipper only follows live streams.
2. **Pick a layout** by looking at one frame of the stream. Grab one with `streamlink --stdout https://twitch.tv/<ch> best | ffmpeg -i pipe:0 -frames:v 1 -y frame.jpg`, then Read the image.
   - `blur` (default): the whole 16:9 frame centred over a blurred fill. Safe for any stream.
   - `crop`: centre crop. Use it for IRL or when the action is in the middle.
   - `split`: facecam on top, gameplay below. Pass `--cam x:y:w:h` measured from the frame (in source pixels, usually 1920x1080).
3. **Launch**, then confirm `events.log` shows `LIVE - recording`.
4. **Force a clip to test it:** `touch clips-<ch>/CLIP_NOW`. Wait ~40s and check that `short.mp4` exists and looks right. Read a frame: `ffmpeg -ss 5 -i short.mp4 -frames:v 1 f.jpg`.
5. **Tune** if it is clipping too much or too little (see the table below).
6. **Uploads:** without `--upload`, each clip's `meta.json` holds an auto title, the transcript and the top chat messages. Write a better title from those, then upload:
   `uv run $S/upload_short.py --meta clips-<ch>/clips/<id>/meta.json --title "..." --privacy public`

## Tuning

| Symptom | Fix |
|---|---|
| Too many clips (huge chat) | `--mult 4 --floor 40 --cooldown 90` |
| No clips (small chat, <2k viewers) | `--mult 2.5 --floor 6` |
| Clip starts after the funny part | raise `--pre` (chat lags the moment by 5–15s) |
| Clip cuts off the reaction | raise `--post` |
| Wrong caption language | `--lang en` (default is auto-detect) |
| Captions slow on an old Mac | `WHISPER_MODEL=base bash setup.sh` then `--model ~/.cache/whisper/ggml-base.bin` |
| YouTube: clips fire late or never | YouTube only shows a sample of chat (Top chat) in ~5s batches. Sampled chat is flatter (bursts are ~2-3x, not 5x), so the defaults are `--mult 2 --floor 6 --chat-delay 10`. Lower `--floor` to 4 for small streams |
| Multiple streamers | one clipper process per channel, each with its own `--out` |

How spikes are scored: unique chatters in the last 5s, plus 0.5 for each hype message (KEKW, LUL, POG, W, "clip it", ???). A spike fires when that score is at least `mult` × the median of the previous 3 minutes and at least `floor`. Unique chatters make it resistant to spam.

## YouTube specifics

- Chat comes from `yt-dlp --write-subs --sub-langs live_chat` (followed live). Each message's own `timestampUsec` is used, so batching doesn't blur timing. The `chat_downloader` package is broken against current YouTube, so don't swap it in.
- The folder and title label is the YouTube channel name (override it with `--name`).

## Outputs

```
clips-<ch>/
  events.log            LIVE / SPIKE / CLIP READY / UPLOAD lines (tail -f this)
  chat.jsonl            full chat log with timestamps
  CLIP_NOW              touch to force a clip
  clips/<YYYYmmdd-HHMMSS>/
     raw.mp4  short.mp4  captions.srt  captions.ass  meta.json
```

## YouTube setup (one time, about 5 minutes)

1. console.cloud.google.com → create a project → **Enable "YouTube Data API v3"**.
2. OAuth consent screen → External → add yourself as a **Test user**.
3. Credentials → Create **OAuth client ID** → type **Desktop app** → download the JSON to `~/.config/live-clipper/client_secret.json`.
4. `uv run $S/upload_short.py --auth` opens a browser. Log in to the channel's Google account. The token is saved to `~/.config/live-clipper/youtube-token.json` (chmod 600).

A file counts as a Short when it is vertical, ≤ 3 min, and has `#Shorts` in the title or description. The uploader adds `#Shorts` when it is missing and sets the category to Gaming.

## Gotchas (read before promising "auto-upload public")

- **Unverified API projects can only upload private videos.** Google locks uploads from unaudited projects to private, even with `--privacy public`. Until the project passes the YouTube API audit, upload private and flip videos to public in YouTube Studio, or apply for the audit. Tell the user this up front.
- **Quota:** each upload costs about 1,600 of the default 10,000 units per day, so about 6 uploads per day. Raising `--mult`/`--floor` or reviewing clips before upload avoids burning it on weak clips.
- **Rights:** the clips are someone else's stream. Credit the channel (the default description does), and make sure the user has the streamer's permission or a clipping program, or knows the risk. Copyright claims and strikes land on the uploading channel. Game footage can also trigger Content ID.
- **Ads:** `--twitch-disable-ads` skips mid-roll ad segments. The buffer has a gap during ads, so a clip near an ad is shorter.
- **It only works while they're live.** Start it before the stream goes live: it polls every 15s and begins recording the moment the stream starts.
- **Disk:** 1080p60 is about 3.5 GB/hour. Only `--keep-minutes` worth is kept, but finished clips stay.

## Common mistakes

- Starting it as a hidden background job and then losing track of it. Use a visible tab and `tail -f events.log`.
- Cutting from a single growing `.ts` file with `-ss`. Seeking in a live file is unreliable. The segment buffer plus the wall-clock index is why clips land on the right moment.
- Clipping at the spike time itself. Chat reacts *after* the moment, so the window is weighted backwards (`--pre 22 --post 8`).
- Promising public auto-uploads without checking the audit status (see Gotchas).
