"""Pretend to be a smart bin: post weigh-ins to the server like the real scale and camera would.

Usage:
    uv run python scripts/simulate_bin.py --bin NS-01 --count 20
    uv run python scripts/simulate_bin.py --bin SS-01 --closing        # vendors dump unsold food
    uv run python scripts/simulate_bin.py --bin NS-01 --photo plate.jpg --stall cr
"""

import argparse
import json
import mimetypes
import random
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path


def request(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read() or b"{}").get("detail", e.reason)
        raise SystemExit(f"Server refused weigh-in ({e.code}): {detail}")


def multipart(fields: dict[str, str], photo: Path | None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    if photo:
        ctype = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{photo.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode() + photo.read_bytes() + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--bin", default="NS-01")
    p.add_argument("--stall", help="Stall id; random stall at this bin if omitted")
    p.add_argument("--count", type=int, default=10, help="Number of customer plates")
    p.add_argument("--closing", action="store_true", help="Each stall dumps its unsold food instead")
    p.add_argument("--photo", type=Path, help="Send this photo so the server identifies the dish")
    p.add_argument("--interval", type=float, default=0.5, help="Seconds between weigh-ins")
    args = p.parse_args()

    locations = request(f"{args.server}/api/locations")
    loc = next((l for l in locations if any(b["id"] == args.bin for b in l["bins"])), None)
    if loc is None:
        sys.exit(f"Unknown bin {args.bin}")
    stalls = [s for s in loc["stalls"] if not args.stall or s["id"] == args.stall]
    if not stalls:
        sys.exit(f"Stall {args.stall} is not served by bin {args.bin}")

    jobs = (
        [(s, "vendor", round(random.uniform(1, 6), 3)) for s in stalls]
        if args.closing
        else [(random.choice(stalls), "plate", round(random.uniform(0.04, 0.25), 3)) for _ in range(args.count)]
    )
    for stall, source, weight in jobs:
        fields = {"stall_id": stall["id"], "source": source, "weight_kg": str(weight)}
        if not args.photo:
            fields["dish"] = random.choice(stall["menu"])  # stands in for an on-device label
        body, ctype = multipart(fields, args.photo)
        res = request(f"{args.server}/api/bins/{args.bin}/drops", body, {"Content-Type": ctype}, "POST")
        d = res["drop"]
        print(f"{args.bin}  {stall['name']:<16} {source:<6} {weight:6.3f} kg  {d['dish'] or 'unidentified'} "
              f"[{d['classified_by']}]  bin load {res['bin_load_kg']:.1f} kg")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
