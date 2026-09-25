"""Offline audit only: python -m probe.unified [vendor-stock.bin]. No BLE imports."""
import argparse
import json
from pathlib import Path

from whip.fwunified import audit_stock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path,
                        default=Path("firmware/rt02cr-stock-3.12.02.bin"))
    args = parser.parse_args()
    audit = audit_stock(args.image.read_bytes())
    print(json.dumps(audit.as_dict(), indent=2))
    return 1 if audit.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
