---
id: dependencies-01
dimension: dependencies
status: gold
domain: scripting
sentinel: false
---

# Task

Script needs to GET a JSON endpoint with a few retries — the host drops
connections occasionally.

# Context

A standalone maintenance script, run weekly from cron. The project currently
has no third-party HTTP dependency.

## A (handroll)

Standard library only, so the script stays dependency-free:

```python
import json, time, urllib.request

def get_json(url, attempts=3):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                return json.load(resp)
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
```

## B (library)

`requests` plus its built-in retry adapter — battle-tested handling of the
edge cases (redirects, encodings, connection reuse):

```python
import requests
from requests.adapters import HTTPAdapter, Retry

session = requests.Session()
session.mount("https://", HTTPAdapter(
    max_retries=Retry(total=3, backoff_factor=1,
                      status_forcelist=[502, 503, 504])))

def get_json(url):
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()
```

Adds `requests` to the environment (`pip install requests`).

# Notes

Both retry three times with backoff and return parsed JSON. A keeps the
project dependency-free at the cost of hand-maintained retry logic; B adds a
ubiquitous dependency and gets richer HTTP semantics for free. Neither is a
strawman; the axis is the dependency itself.
