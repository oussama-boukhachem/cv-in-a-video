#!/usr/bin/env python3
"""cv-in-a-video -- core codec.

Pipeline: file -> zlib -> AES-256-GCM -> chunk -> base85 ASCII -> QR frame.

Why base85 and not raw bytes in the QR?
    zbar hands back bytes as UTF-8, which mangles anything >= 0x80 -- a chunk
    of ciphertext is guaranteed to contain those. base85 (stdlib b85encode) is
    printable ASCII, costs 25% payload, and sidesteps the whole bug class.

Frame layout:
    header frame : {"magic":"CVVD1", ...} JSON, one QR
    data frame   : 5-char zero-padded index + base85 chunk, one QR
"""

import base64
import hashlib
import json
import os
import zlib

import qrcode
from PIL import Image, ImageDraw, ImageFont

MAGIC = b"CVVD1"
VERSION = 1
IDX_WIDTH = 5

MAX_QR_ASCII = 2300  # version 40, EC level M, before qrcode lib gives up


def derive_key(password, salt, iterations=200_000):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, 32)


def compress_bytes(raw):
    c = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY)
    return c.compress(raw) + c.flush()


def build_payload(src_path, password, chunk_size=None, compress=True):
    """Return (chunks, header). Header is public metadata; chunks are secret.

    chunk_size defaults to whatever keeps a chunk's base85 form inside the
    largest QR symbol, so 'just works' == 'biggest frame you can make'.
    """
    with open(src_path, "rb") as f:
        raw = f.read()

    plain = compress_bytes(raw) if compress else raw

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(password, salt)

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise SystemExit("missing cryptography -- pip install cryptography") from e

    ct = AESGCM(key).encrypt(nonce, plain, MAGIC)

    if chunk_size is None:
        # base85 inflates by 1.25x; keep header chars out of the budget
        chunk_size = int((MAX_QR_ASCII - IDX_WIDTH - 8) / 1.25)
        chunk_size -= chunk_size % 40

    chunks = [ct[i:i + chunk_size] for i in range(0, len(ct), chunk_size)]

    header = {
        "magic": MAGIC.decode(),
        "version": VERSION,
        "filename": os.path.basename(src_path),
        "size": len(raw),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "ciphertext_sha256": hashlib.sha256(ct).hexdigest(),
        "chunk_size": chunk_size,
        "chunk_count": len(chunks),
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "kdf_iterations": 200000,
        "compression": "zlib-9" if compress else "none",
    }
    return chunks, header


def encode_chunk(index, chunk):
    return ("%05d" % index) + base64.b85encode(chunk).decode("ascii")


def decode_chunk(text):
    """Return (index, bytes), or None if this is not a data frame."""
    if len(text) <= IDX_WIDTH or not text[:IDX_WIDTH].isdigit():
        return None
    try:
        return int(text[:IDX_WIDTH]), base64.b85decode(text[IDX_WIDTH:])
    except Exception:
        return None


def _font(size=28):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _qr_image(data, px):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(data, optimize=0)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")
    return img.resize((px, px), Image.NEAREST)


def render_frame(width, height, header, chunk_index, chunk_count, payload, tag=""):
    img = Image.new("RGB", (width, height), (14, 14, 18))
    d = ImageDraw.Draw(img)
    f_big, f_small = _font(34), _font(24)

    qr_px = int(min(width, height) * 0.78)
    qr_px -= qr_px % 4
    ox, oy = (width - qr_px) // 2, int(height * 0.045)
    img.paste(_qr_image(payload, qr_px).convert("RGB"), (ox, oy))

    label = ("HEADER %s" % tag) if chunk_index is None else \
        ("chunk %05d/%05d" % (chunk_index + 1, chunk_count))

    lines = [
        label,
        "%s   *   %d bytes   *   %d chunks x %dB" % (
            header["filename"], header["size"], header["chunk_count"],
            header["chunk_size"]),
        "sha256 %s..." % header["ciphertext_sha256"][:32],
    ]

    y = int(height * 0.86)
    for i, line in enumerate(lines):
        t = f_big if i == 0 else f_small
        d.text(((width - d.textlength(line, font=t)) // 2, y + i * 40), line,
               font=t, fill=(235, 235, 240))

    d.rectangle([0, 0, width - 1, height - 1], outline=(60, 60, 70), width=2)
    return img


def render_header_frames(width, height, header, n):
    htext = json.dumps(header, sort_keys=True)
    return [render_frame(width, height, header, None, header["chunk_count"], htext,
                         tag="%d/%d" % (k + 1, n)) for k in range(n)]
