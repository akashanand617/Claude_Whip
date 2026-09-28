"""Compare a prompted phone capture with the RT02 gesture corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from whip.domain_analysis import analyse, json_ready, markdown_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--sessions", type=Path, default=Path("data/sessions"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyse(args.capture, args.checkpoint, args.sessions)
    rendered = markdown_report(report)
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        args.output.with_suffix(".json").write_text(json.dumps(json_ready(report), indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
