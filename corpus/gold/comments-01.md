---
id: comments-01
dimension: comments
status: gold
domain: python-backend
sentinel: false
---

# Task

Add retry with exponential backoff to `fetch_page` — the upstream API throws
occasional 503s.

# Context

An internal sync worker. The team's tolerance for comment density is the
variable; both versions have identical logic.

## A (sparse)

```python
def fetch_page(url, attempts=4):
    delay = 0.5
    for attempt in range(attempts):
        resp = session.get(url, timeout=10)
        if resp.status_code != 503:
            resp.raise_for_status()
            return resp.json()
        # full jitter: herd of workers must not retry in lockstep
        time.sleep(delay * random.random())
        delay *= 2
    raise UpstreamUnavailable(url)
```

## B (narrated)

```python
def fetch_page(url, attempts=4):
    # start with a half-second base delay
    delay = 0.5
    for attempt in range(attempts):
        # make the request
        resp = session.get(url, timeout=10)
        # anything other than 503 is either success or a real error
        if resp.status_code != 503:
            resp.raise_for_status()
            return resp.json()
        # sleep a random fraction of the delay (full jitter), so a herd of
        # workers does not retry in lockstep
        time.sleep(delay * random.random())
        # double the delay for the next attempt
        delay *= 2
    # all attempts exhausted
    raise UpstreamUnavailable(url)
```

# Notes

Code is line-for-line identical; only comment density differs. A keeps the one
comment that states a non-obvious constraint (jitter rationale); B narrates
every step. The jitter comment appears in both so B is a superset, not a
different explanation.
