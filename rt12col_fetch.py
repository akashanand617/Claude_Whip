"""Find and verify stock firmware for RT12COL_V1.0 (DE07). Read-only: never talks to the ring.

    python rt12col_fetch.py
    python rt12col_fetch.py --verify some.bin

Step 1 asks the QRing OTA lookup (app-update/last-ota) the same way the app does, per
Nosh118/colmi-ring-tools docs/research.md. The body encoding and token header are not
documented there, so this tries JSON and form bodies with the token in a header. Every raw
response is printed so you can see what the server actually wants.

Step 2 tries the exact CDN name for the installed build.

Anything found is downloaded and checked: QRing wrapper magic, body sum, and that the
hardware string inside the file is RT12COL_V1.0. A file that fails any check is not a
rollback image.
"""
import argparse
import hashlib
import json
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

HW = "RT12COL_V1.0"
ROM = "RT12COL_1.00.00_260520"
BASES = ["https://api2.qcwxkjvip.com/qcwx/", "https://api1.qcwxkjvip.com/qcwx/",
         "http://api2.qcwxkjvip.com/qcwx/", "https://china.qcwxwire.com/qcwx/"]
# Current build first, then an older-looking one so the server thinks an update is due.
ROMS = [ROM, "RT12COL_1.00.00_000000"]
CDN = [f"http://api2.qcwxkjvip.com/download/ota/{HW}/{ROM}.bin",
       f"http://api1.qcwxkjvip.com/download/ota/{HW}/{ROM}.bin"]


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, repr(e).encode()


def verify(blob):
    """Return a list of problems. Empty list means it looks like a stock RT12COL OTA image."""
    problems = []
    if len(blob) < 0x460:
        return [f"too small: {len(blob)} bytes"]
    magic = struct.unpack("<I", blob[0:4])[0]
    stored_sum = struct.unpack("<I", blob[0x0C:0x10])[0]
    real_sum = sum(blob[0x50:])
    fw = blob[0x10:0x30].split(b"\0")[0].decode(errors="replace")
    hw = blob[0x30:0x50].split(b"\0")[0].decode(errors="replace")
    flags = blob[0x52:0x54].hex()
    print(f"    size {len(blob)}  sha256 {hashlib.sha256(blob).hexdigest()}")
    print(f"    magic 0x{magic:08x}  fw '{fw}'  hw '{hw}'  realtek flags {flags}")
    print(f"    body sum stored {stored_sum} computed {real_sum}")
    if magic != 0x81BDC3E5:
        problems.append("wrong wrapper magic")
    if stored_sum != real_sum:
        problems.append("body sum mismatch")
    if hw != HW:
        problems.append(f"hardware string is '{hw}', not {HW}")
    if not fw.startswith("RT12COL_"):
        problems.append(f"firmware string '{fw}' is not an RT12COL build")
    return problems


ap = argparse.ArgumentParser()
ap.add_argument("--verify", help="only verify a local .bin")
args = ap.parse_args()

if args.verify:
    problems = verify(open(args.verify, "rb").read())
    print("OK" if not problems else "FAIL: " + "; ".join(problems))
    sys.exit(1 if problems else 0)

found = set()

print("== step 1: OTA lookup")
for base in BASES:
    status, body = http(base + "token/getToken?key=qcwx_android")
    print(f"\n{base}token/getToken -> {status}\n  {body[:300]!r}")
    token = ""
    try:
        j = json.loads(body)
        token = j.get("data") if isinstance(j.get("data"), str) else (j.get("data") or {}).get("token", "") or j.get("token", "")
    except Exception:
        pass
    for rom in ROMS:
        fields = {"appId": "", "uid": "", "hardwareVersion": HW, "romVersion": rom,
                  "os": "android", "mac": "", "country": "US", "dev": ""}
        attempts = [
            ("json", json.dumps(fields).encode(), {"Content-Type": "application/json"}),
            ("form", urllib.parse.urlencode(fields).encode(),
             {"Content-Type": "application/x-www-form-urlencoded"}),
        ]
        for kind, data, headers in attempts:
            if token:
                headers = dict(headers, token=token, Authorization=token)
            for path in ["app-update/last-ota", "app-update/last-ota/china"]:
                status, body = http(base + path, data, headers)
                print(f"  POST {path} [{kind}, rom={rom}] -> {status}\n    {body[:400]!r}")
                for url in re.findall(rb'https?://[^"\s]+?\.bin', body):
                    found.add(url.decode())

print("\n== step 2: exact CDN name")
for url in CDN:
    status, body = http(url)
    print(f"  {url} -> {status} ({len(body)} bytes)")
    if status == 200 and len(body) > 0x460:
        found.add(url)

print("\n== results")
if not found:
    print("No firmware URL found. Paste the raw responses above back to Claude.")
    sys.exit(1)

for url in sorted(found):
    print(f"\n  {url}")
    status, blob = http(url)
    if status != 200:
        print(f"    download failed: {status}")
        continue
    name = url.rsplit("/", 1)[-1]
    open(name, "wb").write(blob)
    problems = verify(blob)
    print(f"    saved {name}: " + ("OK, usable as RT12COL stock" if not problems else "FAIL: " + "; ".join(problems)))
