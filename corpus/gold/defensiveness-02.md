---
id: defensiveness-02
dimension: defensiveness
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Implement `parse_packet(const uint8_t*, size_t)` for the 16-byte UART frame:
command byte, 14 data bytes, checksum = sum of the first 15 bytes mod 256.

# Context

The daemon's BLE layer hands notification payloads to this function. `Packet`
is `{ uint8_t cmd; uint8_t data[14]; }`. The daemon is built with asserts
enabled in all configurations.

## A (trusting)

```cpp
Packet parse_packet(const uint8_t* buf, size_t len) {
    assert(len == 16);
    uint8_t sum = 0;
    for (size_t i = 0; i < 15; ++i) sum += buf[i];
    assert(sum == buf[15]);
    Packet p;
    p.cmd = buf[0];
    std::memcpy(p.data, buf + 1, 14);
    return p;
}
```

A wrong length or bad checksum means the BLE layer above is broken; the
assert stops the daemon at the fault, with the failing condition in the abort
message.

## B (defensive)

```cpp
enum class ParseError { Ok, BadLength, BadChecksum };

ParseError parse_packet(const uint8_t* buf, size_t len, Packet& out) {
    if (len != 16) return ParseError::BadLength;
    uint8_t sum = 0;
    for (size_t i = 0; i < 15; ++i) sum += buf[i];
    if (sum != buf[15]) return ParseError::BadChecksum;
    out.cmd = buf[0];
    std::memcpy(out.data, buf + 1, 14);
    return ParseError::Ok;
}
```

The caller logs the error value and drops the frame; a corrupted notification
never takes the daemon down.

# Notes

On a well-formed frame both compute the identical checksum and produce the
identical `Packet`. The axis is only how a malformed frame surfaces: abort at
the fault versus an error code the caller handles. Asserts are compiled in,
so A does not silently accept bad frames; B logs every drop, so it does not
hide them either.
