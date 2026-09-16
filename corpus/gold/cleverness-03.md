---
id: cleverness-03
dimension: cleverness
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Find the first packet whose amplitude exceeds the threshold.

# Context

Part of the ring daemon's event scan. `packets` is a `std::vector<Packet>`;
`Packet` has a `float amplitude` member. Return a pointer to the first match,
or `nullptr` when nothing exceeds the threshold.

## A (explicit)

```cpp
const Packet* find_first_loud(const std::vector<Packet>& packets,
                              float threshold) {
    for (size_t i = 0; i < packets.size(); ++i) {
        const Packet& packet = packets[i];
        if (packet.amplitude > threshold) {
            return &packet;
        }
    }
    return nullptr;
}
```

## B (dense)

```cpp
const Packet* find_first_loud(const std::vector<Packet>& packets,
                              float threshold) {
    auto it = std::find_if(packets.begin(), packets.end(),
        [&](const Packet& p) { return p.amplitude > threshold; });
    return it != packets.end() ? &*it : nullptr;
}
```

# Notes

Same signature, same return for every input, same single pass with early
exit. A is an indexed loop with a named reference and an explicit early
return; B is the standard-algorithm form -- `std::find_if` plus a lambda and
a conditional expression. Neither is exotic C++; the axis is whether the
`<algorithm>` vocabulary reads as clearer or as denser than the loop it
replaces. The dense variant is the shorter one here.
