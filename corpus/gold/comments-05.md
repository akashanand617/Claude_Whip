---
id: comments-05
dimension: comments
status: gold
domain: embedded
sentinel: false
---

# Task

Implement the packet checksum (sum of bytes mod 256) for outgoing frames.

# Context

Firmware-side framing for the 16-byte UART protocol: the last byte of every
frame is the sum of the preceding bytes modulo 256. Both versions have
identical logic.

## A (sparse)

```c
uint8_t checksum(const uint8_t *frame, size_t len) {
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++)
        sum += frame[i];
    return sum;
}
```

## B (narrated)

```c
/* checksum = sum of all preceding frame bytes, modulo 256 */
uint8_t checksum(const uint8_t *frame, size_t len) {
    /* accumulate in a uint8_t so wraparound gives the mod 256 for free */
    uint8_t sum = 0;
    /* add every byte of the frame */
    for (size_t i = 0; i < len; i++)
        sum += frame[i];
    /* the truncated sum is the checksum byte */
    return sum;
}
```

# Notes

Code is line-for-line identical; only comment density differs. A has zero
comments -- deliberate: the function is three lines and nothing in it is a
non-obvious constraint, so the sparse pole here means none at all. B restates
the algorithm in a header comment and narrates each line. With no constraint
comment in A, the superset rule is satisfied vacuously.
