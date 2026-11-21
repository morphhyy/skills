# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["google-api-python-client>=2.100", "google-auth-oauthlib>=1.2"]
# ///
"""Upload a vertical clip to YouTube Shorts via the YouTube Data API v3.

    uv run upload_short.py --auth                          # one-time browser login
    uv run upload_short.py --meta clips/<id>/meta.json     # upload using meta.json
    uv run upload_short.py --file short.mp4 --title "..."  # upload any file

Needs an OAuth "Desktop app" client from Google Cloud saved as
~/.config/live-clipper/client_secret.json (YouTube Data API v3 enabled).
"""
import argparse, json, os, sys
from pathlib import Path

CFG = Path.home() / ".config" / "live-clipper"
SECRET, TOKEN = CFG / "client_secret.json", CFG / "youtube-token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    c = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if c and c.valid:
        return c
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
    else:
        if not SECRET.exists():
            sys.exit(f"missing {SECRET} - create an OAuth Desktop client (see SKILL.md)")
        c = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES).run_local_server(port=0)
    CFG.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(TOKEN, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # never world-readable, even briefly
    with os.fdopen(fd, "w") as f:
        f.write(c.to_json())
    TOKEN.chmod(0o600)   # tighten a pre-existing file too
    return c


def upload(path, title, desc, tags, privacy):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    if "#shorts" not in (title + desc).lower():
        desc += "\n#Shorts"
    yt = build("youtube", "v3", credentials=creds())
    body = {"snippet": {"title": title[:100], "description": desc[:5000],
                        "tags": tags, "categoryId": "20"},          # 20 = Gaming
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(path), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--auth", action="store_true", help="just log in and save the token")
    p.add_argument("--meta")
    p.add_argument("--file")
    p.add_argument("--title")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="gaming,shorts,twitch")
    p.add_argument("--thumb", help="custom thumbnail image (jpg/png, <2MB)")
    p.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    a = p.parse_args()
    if a.auth:
        creds(); print(f"OK token saved to {TOKEN}"); return
    meta = json.loads(Path(a.meta).read_text()) if a.meta else {}
    path = Path(a.file or meta.get("file", ""))
    title = a.title or meta.get("title")
    if not path.exists() or not title:
        sys.exit("need --meta or --file + --title")
    desc = a.description or meta.get("description", "")
    tags = [t for t in a.tags.split(",") if t] + ([meta["channel"]] if meta.get("channel") else [])
    vid = upload(path, title, desc, tags, a.privacy)
    url = f"https://youtube.com/shorts/{vid}"
    if a.thumb:
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            build("youtube", "v3", credentials=creds()).thumbnails().set(
                videoId=vid, media_body=MediaFileUpload(a.thumb)).execute()
            print("THUMBNAIL set")
        except Exception as e:
            print(f"THUMBNAIL failed: {str(e)[:200]}")
    if a.meta:
        meta["uploaded"] = {"id": vid, "url": url, "privacy": a.privacy}
        Path(a.meta).write_text(json.dumps(meta, indent=2))
    print(f"UPLOADED {url} ({a.privacy})")


if __name__ == "__main__":
    main()
