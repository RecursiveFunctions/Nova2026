#!/usr/bin/env python3
"""Printable QR stickers for the boxes (pip install qrcode pillow).

    python make_qr.py                                              # uses PUBLIC_URL / novabox default
    python make_qr.py --public-url https://novabox.recursivefunctions.dev/keyaan
    python make_qr.py --box BOX-01

Each sticker opens <public-url>/pickup/<box> (e.g. /<branch>/pickup/BOX-01). Staff mark ready
there; couriers enter the one-time code. Prefer the public hostname over a LAN IP.
"""
import argparse
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bridge import _font, make_qr  # noqa: E402  (same QR settings as the box screen)


def sticker(url: str, box_id: str):
    from PIL import Image, ImageDraw
    qr_size, pad = 600, 40
    img = Image.new("RGB", (qr_size + 2 * pad, qr_size + 2 * pad + 150), "white")
    img.paste(make_qr(url, qr_size), (pad, pad))
    d = ImageDraw.Draw(img)
    d.text((img.width // 2, qr_size + pad + 20), box_id, font=_font(56), fill="black", anchor="mt")
    d.text((img.width // 2, qr_size + pad + 95), "Scan to pick up or mark ready", font=_font(30),
           fill=(80, 80, 80), anchor="mt")
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--public-url",
                    default=os.environ.get("PUBLIC_URL") or "https://novabox.recursivefunctions.dev",
                    help="origin phones open, optionally with /<branch> (env PUBLIC_URL)")
    ap.add_argument("--box", action="append", help="box ID; repeat for several (default BOX-01 and BOX-02)")
    ap.add_argument("--out", default=".", help="output folder")
    args = ap.parse_args()
    if "localhost" in args.public_url or "127.0.0.1" in args.public_url:
        sys.exit("Use https://novabox.recursivefunctions.dev[/branch], not localhost.")
    for box_id in args.box or ["BOX-01", "BOX-02"]:
        url = f"{args.public_url.rstrip('/')}/pickup/{urllib.parse.quote(box_id, safe='')}"
        path = os.path.join(args.out, f"qr-{box_id}.png")
        sticker(url, box_id).save(path)
        print(f"{path}  ->  {url}")


if __name__ == "__main__":
    main()
