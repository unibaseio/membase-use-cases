#!/bin/bash
# Record a hosted demo's video on a fresh test account, and try again on another account
# (at most 3 times) when the take cannot show what it should: a course or bible that did not
# learn, a learning run that failed mid-take, and so on.
#
#   scripts/video/record_hosted.sh 04-story-bible --containers "Story Bible" --read-key
#
# Arguments after the demo go to bootstrap_hosted.py. The demo's seed.py runs first.
set -u
cd "$(dirname "$0")/../.."
demo=$1; shift
for try in 1 2 3; do
  name="video-${demo%%-*}-try$try-$(date +%H%M%S)"
  echo "== try $try: $name"
  .venv/bin/python scripts/bootstrap_hosted.py --name "$name" "$@" || continue
  if [ -f "$demo/seed.py" ]; then
    DEMO_ENV_FILE=".secrets/$name.env" timeout 1800 .venv/bin/python "$demo/seed.py" || { echo "seed not ready"; continue; }
  fi
  DEMO_ENV_FILE=".secrets/$name.env" timeout 3000 .venv/bin/python scripts/video/make.py "$demo" && { echo "RECORDED on $name"; exit 0; }
  echo "take failed"
done
exit 1
