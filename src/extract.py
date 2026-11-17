#!/usr/bin/env python3
"""Phase 2: pull the file back out of a video (local mp4 or yt-dlp download).

Usage:
    python src/extract.py --in out/cv-video.mp4 --out out/restored.txt --password hunter2

Every frame is decoded independently. Missing or duplicate chunks are fine as
long as every index shows up at least once. Final proof: SHA-256 on the
ciphertext, then the AES-GCM tag, then SHA-256 on the plaintext.
"""
import argparse
import hashlib
import json
import os
import sys
import zlib

import cv2
from pyzbar.pyzbar import decode as zbar_decode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codec  # noqa: E402


def frames(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("cannot open %s" % path)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        yield frame
    cap.release()


def try_decode(frame):
    """QR strings in this frame, retrying at 2x for small modules."""
    def _read(img):
        return [s.data.decode("ascii", "replace") for s in zbar_decode(img)
                if s.type == "QRCODE"]

    got = _read(frame)
    if got:
        return got
    h, w = frame.shape[:2]
    return _read(cv2.resize(frame, (w * 2, h * 2), interpolation=cv2.INTER_NEAREST))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--password", default=None)
    args = ap.parse_args()

    password = args.password or os.environ.get("CVVIDEO_PASSWORD")
    if not password:
        raise SystemExit("need --password or CVVIDEO_PASSWORD")

    header, chunks, seen = None, {}, 0

    for frame in frames(args.src):
        seen += 1
        for text in try_decode(frame):
            if text.startswith("{"):
                try:
                    h = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if h.get("magic") == "CVVD1":
                    header = h
                continue
            parsed = codec.decode_chunk(text)
            if parsed is None or header is None:
                continue
            idx, data = parsed
            if idx < header["chunk_count"]:
                chunks[idx] = data

    if header is None:
        raise SystemExit("no header frame found -- wrong video or unreadable")

    need = header["chunk_count"]
    missing = [i for i in range(need) if i not in chunks]
    print("frames scanned: %d, chunks: %d/%d, missing: %d"
          % (seen, len(chunks), need, len(missing)))
    if missing:
        raise SystemExit("missing chunks %s -- re-encode with --repeat 2" % missing[:10])

    ct = b"".join(chunks[i] for i in range(need))
    if hashlib.sha256(ct).hexdigest() != header["ciphertext_sha256"]:
        raise SystemExit("ciphertext SHA-256 mismatch -- a chunk decoded wrong")

    key = codec.derive_key(password, bytes.fromhex(header["salt"]),
                           header["kdf_iterations"])
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    plain = AESGCM(key).decrypt(bytes.fromhex(header["nonce"]), ct, codec.MAGIC)

    if header["compression"].startswith("zlib"):
        plain = zlib.decompress(plain)

    import hashlib as _h
    actual = _h.sha256(plain).hexdigest()
    if actual != header["payload_sha256"]:
        raise SystemExit("plaintext SHA-256 mismatch %s != %s"
                         % (actual[:16], header["payload_sha256"][:16]))

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    with open(args.dst, "wb") as f:
        f.write(plain)
    print("OK  restored -> %s (%d B, sha256 matches)" % (args.dst, len(plain)))


if __name__ == "__main__":
    main()
