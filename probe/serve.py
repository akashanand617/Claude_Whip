"""
Run the ring console.

    python -m probe.serve
    python -m probe.serve --port 8642 --checkpoint data/model.pt

Then open http://127.0.0.1:8642 -- live gesture tracking, gesture->action
settings, and stock <-> gesture firmware flashing, all against the ring this
machine can see. Loopback only, deliberately.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whip import server


def main() -> int:
    parser = argparse.ArgumentParser(description="Ring console web app")
    parser.add_argument("--port", type=int, default=server.PORT)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    args = parser.parse_args()
    server.main(checkpoint=args.checkpoint, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
