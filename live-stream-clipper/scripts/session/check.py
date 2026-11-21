# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["google-api-python-client>=2.100", "google-auth-oauthlib>=1.2"]
# ///
import sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
c = Credentials.from_authorized_user_file(str(Path.home()/".config/live-clipper/youtube-token.json"))
if not c.valid: c.refresh(Request())
yt = build("youtube", "v3", credentials=c)
for it in yt.videos().list(part="snippet,status", id=",".join(sys.argv[1:])).execute()["items"]:
    t = it["snippet"]["thumbnails"]
    print(it["id"], it["status"]["privacyStatus"], it["snippet"]["title"][:50], "|", t.get("maxres", t.get("high"))["url"])
