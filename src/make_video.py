#!/usr/bin/env python3
"""Phase 1: encode a file into a QR-stream video.

Usage:
    python src/make_video.py --in samples/cv.txt --out out/cv-video.mp4 --password hunter2

Every frame is independently decodable on purpose (H.264 -g 1, CRF 18), because
YouTube re-encodes everything and one interframe would cost you the restore.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codec  # noqa: E402

FPS = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--password", default=None, help="default: env CVVIDEO_PASSWORD")
    ap.add_argument("--chunk-size", type=int, default=1800)
    ap.add_argument("--header-frames", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--workdir", default="out/_frames")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    password = args.password or os.environ.get("CVVIDEO_PASSWORD")
    if not password:
        raise SystemExit("need --password or CVVIDEO_PASSWORD")

    chunks, header = codec.build_payload(args.src, password, args.chunk_size)
    print("payload: %d B -> %d chunks of %d B (ciphertext %d B)" % (
        header["size"], header["chunk_count"], header["chunk_size"],
        sum(len(c) for c in chunks)))

    os.makedirs(args.workdir, exist_ok=True)
    for f in os.listdir(args.workdir):
        os.remove(os.path.join(args.workdir, f))

    n = 0
    for img in codec.render_header_frames(args.width, args.height, header, args.header_frames):
        img.save(os.path.join(args.workdir, "%06d.png" % n))
        n += 1

    for _ in range(args.repeat):
        for i, ch in enumerate(chunks):
            payload = codec.encode_chunk(i, ch)
            codec.render_frame(args.width, args.height, header, i,
                               header["chunk_count"], payload) \
                .save(os.path.join(args.workdir, "%06d.png" % n))
            n += 1
            if n % 25 == 0:
                print("  %d frames" % n, flush=True)

    print("rendered %d frames, encoding video..." % n)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", os.path.join(args.workdir, "%06d.png"),
        "-c:v", "libx264", "-preset", "slow", "-g", "1", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        args.out,
    ], check=True)

    dur = n / FPS
    print("video: %s (%d frames, %.0fs @ %d fps)" % (args.out, n, dur, FPS))

    side = os.path.splitext(args.out)[0] + ".header.json"
    with open(side, "w") as f:
        json.dump(header, f, indent=2)
    print("header: %s" % side)

    if not args.keep_frames:
        for f in os.listdir(args.workdir):
            os.remove(os.path.join(args.workdir, f))


if __name__ == "__main__":
    main()
