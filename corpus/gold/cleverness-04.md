---
id: cleverness-04
dimension: cleverness
status: gold
domain: scripting
sentinel: false
---

# Task

Extract the unique client IPs from the access log.

# Context

One-off triage during an incident. `access.log` is standard combined format:
every line is one request record and the client IP is the first
whitespace-separated field. Output is the sorted unique IPs, one per line.

## A (explicit)

```python
ips = set()
with open("access.log") as f:
    for line in f:
        ip = line.split()[0]
        ips.add(ip)

for ip in sorted(ips):
    print(ip)
```

## B (dense)

```sh
awk '{print $1}' access.log | sort -u
```

# Notes

Identical output on the stated format: both take field one, deduplicate, and
emit in lexicographic order. A is a small Python script with named
intermediates; B is the classic three-stage shell pipeline. For a one-off on
a well-formed log neither is over- or under-engineered -- the axis is whether
the terse Unix idiom is preferred over spelled-out code, not whether either
works. The dense variant is much shorter.
