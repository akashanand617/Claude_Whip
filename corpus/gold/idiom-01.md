---
id: idiom-01
dimension: idiom
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Add a `batteryPercent()` accessor to `RingState` in `ring_state.h`.

# Context

A legacy C++ header that consistently uses `#define` constants, camelCase
methods, raw `int` types, and no `[[nodiscard]]` anywhere. The project style
guide is silent; the file is its own precedent.

## A (conform)

Matches the file as it stands:

```cpp
#define BATTERY_UNKNOWN -1

int batteryPercent() const {
    if (m_batteryRaw < 0 || m_batteryRaw > 100)
        return BATTERY_UNKNOWN;
    return m_batteryRaw;
}
```

## B (modernize)

Written to current practice; the rest of the file can migrate over time:

```cpp
static constexpr int kBatteryUnknown = -1;

[[nodiscard]] int battery_percent() const noexcept {
    if (m_batteryRaw < 0 || m_batteryRaw > 100)
        return kBatteryUnknown;
    return m_batteryRaw;
}
```

Note this introduces the file's first `constexpr`, `[[nodiscard]]`, and
snake_case method — callers of the new accessor follow the new convention
while everything else stays camelCase.

# Notes

Identical logic and identical behavior. A extends the file's dated idiom
consistently; B writes the modern form and knowingly introduces a style seam.
Both are defensible positions on legacy code; the axis is which the coder
wants by default.
