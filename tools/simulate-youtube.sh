#!/usr/bin/env bash
# Simulate YouTube's transcode to prove the decoder survives it.
#
# YouTube re-encodes to H.264 (often 720p for small channels) with a
# standard preset and then serves that. This does the same: downscale to
# 720p, re-encode, and hand the result to the decoder.
#
#   ./simulate-youtube.sh out/cv-video.mp4 out/cv-video.youtube-sim.mp4
set -euo pipefail
IN="${1:-out/cv-video.mp4}"
OUT="${2:-out/cv-video.youtube-sim.mp4}"

ffmpeg -y -loglevel error -i "$IN" \
  -vf "scale=1280:720:flags=bicubic" \
  -c:v libx264 -preset medium -crf 23 -g 250 -pix_fmt yuv420p \
  -an "$OUT"

echo "simulated upload: $OUT"
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,codec_name \
  -of default=nw=1 "$OUT"
