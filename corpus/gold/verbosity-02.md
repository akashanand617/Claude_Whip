---
id: verbosity-02
dimension: verbosity
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

This crashes intermittently under load — ASAN says the iterator into
`pending_` is dangling. Why?

```cpp
for (auto it = pending_.begin(); it != pending_.end(); ++it)
    if (needs_retry(*it)) pending_.push_back(*it);
```

# Context

The retry queue for unacknowledged BLE frames in the C++17 ring daemon.
`pending_` is a `std::vector<Frame>`; the crash only shows up when the queue
is busy.

## A (terse)

`push_back` can reallocate the vector's storage, which invalidates every
iterator into it — `it` included. Index instead:

```cpp
for (size_t i = 0, n = pending_.size(); i < n; ++i)
    if (needs_retry(pending_[i])) pending_.push_back(pending_[i]);
```

## B (explanatory)

When a `std::vector` is full, `push_back` allocates a larger block, moves the
elements across, and frees the old storage — and every iterator into the old
block, `it` included, now points into freed memory. That is why the crash is
intermittent: it only fires on the pushes where `size()` crosses `capacity()`,
which under light load may be never. When no reallocation happens, existing
iterators survive a `push_back` (only `end()` changes), so the loop can look
correct for a long time.

Index instead, snapshotting the length so freshly appended frames aren't
re-scanned in the same pass:

```cpp
for (size_t i = 0, n = pending_.size(); i < n; ++i)
    if (needs_retry(pending_[i])) pending_.push_back(pending_[i]);
```

`reserve()` before the loop would also prevent reallocation, but that pins
correctness to a capacity invariant holding at a distance; the index form is
locally self-sufficient.

# Notes

Identical diagnosis and byte-identical fix; the axis is purely how much of
the reallocation mechanism is explained around it. B's extra content —
growth semantics, why the crash is intermittent, the reserve() alternative —
is correct, not padding, so a reaction measures appetite for explanation,
not accuracy.
