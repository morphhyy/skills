#!/bin/bash
# retry_parked.sh [interval-seconds]  — every interval, try API upload of every parked clip in output/*.json.
# On success: log to clips-<channel>/uploaded.txt and delete the output/ copies. Exits when output/ has no parked clips.
cd "${CLIPPER_ROOT:-$(cd "$(dirname "$0")/../../../../.." && pwd)}"
S=.claude/skills/live-stream-clipper/scripts
iv=${1:-3600}
while true; do
  shopt -s nullglob; js=(output/*.json); shopt -u nullglob
  [ ${#js[@]} -eq 0 ] && { echo "$(date +%T) DONE no parked clips left"; exit 0; }
  for j in "${js[@]}"; do
    base=${j%.json}; f="$base.mp4"; name=$(basename "$base")
    [ -f "$f" ] || continue
    ch=${name%%-*}; id=${name#*-}
    case $ch in KaiCenat) dir=clips-kaicenat;; IShowSpeed) dir=clips-ishowspeed;; *) dir=clips-$(echo "$ch" | tr A-Z a-z);; esac
    T=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["title"])' "$j")
    D=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["description"])' "$j")
    G=$(python3 -c 'import json,sys;print(",".join(json.load(open(sys.argv[1]))["tags"]))' "$j")
    out=$(uv run --quiet $S/upload_short.py --file "$f" --title "$T" --description "$D" --tags "$G" --privacy public 2>&1)
    if echo "$out" | grep -q UPLOADED; then
      url=$(echo "$out" | grep -o 'https://[^ ]*' | head -1)
      echo "$id $url $T (api retry)" >> $dir/uploaded.txt
      rm -f "$f" "$j" "$base-cover.jpg"
      echo "$(date +%T) UPLOADED $name $url"
    elif echo "$out" | grep -q uploadLimitExceeded; then
      echo "$(date +%T) still capped ($name)" >&2
      break   # cap is channel-wide; no point trying the rest this round
    else
      echo "$(date +%T) ERROR $name: $(echo "$out" | tail -1 | cut -c1-200)"
    fi
  done
  sleep "$iv"
done
