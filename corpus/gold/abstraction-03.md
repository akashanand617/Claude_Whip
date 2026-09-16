---
id: abstraction-03
dimension: abstraction
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Parse the two accelerometer packet subtypes we actually receive.

# Context

The C++ daemon receives 16-byte `A1` packets; byte 1 carries the subtype.
Only `0x03` (accelerometer) and `0x05` (status) ever arrive on this firmware;
the protocol defines up to 16. Unknown subtypes are dropped.

## A (concrete)

Two parse functions, dispatched by a switch:

```cpp
static bool parse_accel(const uint8_t* p, Sample& out) {
    out.y = be16(p + 2); out.z = be16(p + 4); out.x = be16(p + 6);
    out.kind = Kind::Accel;
    return true;
}
static bool parse_status(const uint8_t* p, Sample& out) {
    out.raw = p[2];
    out.kind = Kind::Status;
    return true;
}

bool parse_packet(const uint8_t* p, Sample& out) {
    switch (p[1]) {
    case 0x03: return parse_accel(p, out);
    case 0x05: return parse_status(p, out);
    default:   return false;
    }
}
```

## B (generalized)

The same two parse functions as in the switch version, unchanged; dispatch
becomes a registry a new subtype joins with one line:

```cpp
using Handler = bool (*)(const uint8_t*, Sample&);
struct Entry { uint8_t subtype; Handler fn; };

// one slot per registered subtype; the protocol defines 16, two exist today
static constexpr Entry kHandlers[] = {
    {0x03, parse_accel},
    {0x05, parse_status},
};

bool parse_packet(const uint8_t* p, Sample& out) {
    for (const auto& e : kHandlers)
        if (e.subtype == p[1])
            return e.fn(p, out);
    return false;
}
```

# Notes

The two subtype parsers are identical in both variants, and both dispatchers
return the same result for every input: parsed for 0x03/0x05, false
otherwise. B replaces the switch with a handler table sized for subtypes that
may never be needed. The axis is whether the registry's extensibility is
worth the indirection for a two-case dispatch.
