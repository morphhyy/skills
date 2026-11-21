#!/bin/bash
# up.sh <clip_dir> <title> <description> <tags-csv> <cover-hook> [cover-at-seconds]
cd "${CLIPPER_ROOT:-$(cd "$(dirname "$0")/../../../../.." && pwd)}"
S=.claude/skills/live-stream-clipper/scripts
d="$1"; id=$(basename "$d")
python3 $S/cover.py "$d" --hook "$5" --at "${6:-10}" --label "${LABEL:-SPEED x GTA 6}" --cam "${CAM:-2:916:216:136}" || { echo "COVER FAILED - using plain short"; cp "$d/short.mp4" "$d/final.mp4"; }
thumb=(); [ -f "$d/cover.jpg" ] && thumb=(--thumb "$d/cover.jpg")
out=$(uv run --quiet $S/upload_short.py --file "$d/final.mp4" --title "$2" --description "$3" --tags "$4" --privacy public "${thumb[@]}" 2>&1)
echo "$out" | tail -3
if ! echo "$out" | grep -q UPLOADED; then
  mkdir -p output; cp "$d/final.mp4" "output/${CH:-IShowSpeed}-$id.mp4"; [ -f "$d/cover.jpg" ] && cp "$d/cover.jpg" "output/${CH:-IShowSpeed}-$id-cover.jpg"
  python3 -c 'import json,sys;json.dump({"file":sys.argv[1],"title":sys.argv[2],"description":sys.argv[3],"tags":sys.argv[4].split(","),"error":sys.argv[5][-500:]},open(sys.argv[6],"w"),indent=2)' "${CH:-IShowSpeed}-$id.mp4" "$2" "$3" "$4" "$out" "output/${CH:-IShowSpeed}-$id.json"
  echo "API FAILED -> saved output/${CH:-IShowSpeed}-$id.mp4 ; trying YouTube Studio"
  SP=$S/session
  PW=$(cat ~/.config/live-clipper/pw_path)
  sr=$($PW -s=ytstudio run-code "$(python3 $SP/studio_fill.py "$PWD/output/${CH:-IShowSpeed}-$id.mp4" "output/${CH:-IShowSpeed}-$id.json" "$PWD/output/${CH:-IShowSpeed}-$id-cover.jpg")" 2>&1 | grep -o 'STUDIO_[A-Z]*[^"]*\|LIMIT[^"]*\|Error[^"]*' | head -1)
  echo "STUDIO: $sr"
  if echo "$sr" | grep -qE "STUDIO_(UPLOADED|UNSURE) https"; then
    echo "$id $sr $2 (studio)" >> $(dirname $(dirname "$d"))/uploaded.txt
    rm -f output/${CH:-IShowSpeed}-$id.mp4 output/${CH:-IShowSpeed}-$id.json output/${CH:-IShowSpeed}-$id-cover.jpg
  fi
else
  echo "$id $(echo "$out" | grep -o 'https://[^ ]*') $2" >> $(dirname $(dirname "$d"))/uploaded.txt
fi
