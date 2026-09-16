---
id: comments-02
dimension: comments
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Implement the ring-buffer write with wraparound for the sample queue.

# Context

The C++ ring daemon's sample queue, fed by the single-threaded capture loop.
Capacity is a compile-time power of two, and overwrite-oldest on overflow is
the agreed policy. Both versions have identical logic.

## A (sparse)

```cpp
void SampleQueue::push(const Sample& s) {
    // kCapacity is a power of two: the mask IS the wraparound
    buf_[head_ & (kCapacity - 1)] = s;
    ++head_;
    if (head_ - tail_ > kCapacity)
        tail_ = head_ - kCapacity;
}
```

## B (narrated)

```cpp
void SampleQueue::push(const Sample& s) {
    // write the sample into the slot the head currently points at
    // kCapacity is a power of two: the mask IS the wraparound
    buf_[head_ & (kCapacity - 1)] = s;
    // advance the head; indices grow monotonically, masked only on access
    ++head_;
    // if the head has lapped the tail, the oldest sample was just
    // overwritten -- drag the tail forward to the oldest surviving one
    if (head_ - tail_ > kCapacity)
        tail_ = head_ - kCapacity;
}
```

# Notes

Code is line-for-line identical; only comment density differs. A keeps the one
comment stating the non-obvious constraint (the power-of-two capacity is what
makes masking a valid wraparound); B narrates every step. The invariant
comment appears verbatim in both, so B is a superset, not a different
explanation.
