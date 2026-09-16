---
id: dependencies-03
dimension: dependencies
status: gold
domain: python-backend
sentinel: false
---

# Task

Parse the ISO-8601 durations the partner API sends (`PT1H30M`, `PT45S`,
`PT2H`) into seconds.

# Context

The partner's payloads only ever use the time components H, M, and S, with
an optional fractional seconds part. The value feeds a scheduling
calculation as a float of seconds.

## A (handroll)

The partner's subset fits one regex; no new dependency:

```python
import re

_DURATION = re.compile(
    r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")

def duration_seconds(s: str) -> float:
    m = _DURATION.match(s)
    if not m or not any(m.groups()):
        raise ValueError(f"unsupported duration: {s!r}")
    h, mnt, sec = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mnt * 60 + sec
```

## B (library)

`isodate` implements the full standard:

```python
from isodate import parse_duration

def duration_seconds(s: str) -> float:
    return parse_duration(s).total_seconds()
```

Adds `isodate` (`pip install isodate`). For the partner's `PT...` forms it
returns a plain `timedelta`; week forms like `P2W` and malformed strings
(`ISO8601Error`) are covered without further code.

# Notes

On every form the partner actually sends, both return the same float of
seconds and both raise on malformed input. A covers exactly the observed
subset with twelve owned lines; B adds a small dependency and inherits the
whole standard, including forms that may never arrive. Neither is sloppy --
the regex anchors and rejects, and the library call is the documented API.
