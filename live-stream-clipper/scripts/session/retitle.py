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
vid, title, desc, tags = sys.argv[1:5]
sn = yt.videos().list(part="snippet", id=vid).execute()["items"][0]["snippet"]
body = {"id": vid, "snippet": {"title": title, "description": desc, "tags": tags.split(","),
        "categoryId": sn.get("categoryId", "20")}}
r = yt.videos().update(part="snippet", body=body).execute()
print("UPDATED", r["snippet"]["title"])
