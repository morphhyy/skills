# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["google-api-python-client>=2.100", "google-auth-oauthlib>=1.2"]
# ///
import sys, json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
T = Path.home()/".config/live-clipper/youtube-token.json"
c = Credentials.from_authorized_user_file(str(T))
print("scopes:", json.loads(T.read_text()).get("scopes"))
if not c.valid: c.refresh(Request())
try:
    build("youtube","v3",credentials=c).thumbnails().set(videoId=sys.argv[1], media_body=MediaFileUpload(sys.argv[2])).execute()
    print("THUMBNAIL set")
except Exception as e:
    print("ERR", str(e)[:600])
