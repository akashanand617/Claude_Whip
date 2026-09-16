---
id: proactivity-02
dimension: proactivity
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Add a `clamp(value, lo, hi)` helper to `util.h`.

# Context

The daemon's `util.h` is a small header of free functions with an existing
test file (`tests/test_util.cpp`). The request names only the function.

## A (exact)

Added to `util.h`, matching the header's existing style:

```cpp
template <typename T>
constexpr T clamp(T value, T lo, T hi) {
    return value < lo ? lo : (hi < value ? hi : value);
}
```

Compiles under the project's C++17 flags; usable from any TU that already
includes `util.h`.

## B (collateral)

Added to `util.h`, matching the header's existing style:

```cpp
template <typename T>
constexpr T clamp(T value, T lo, T hi) {
    return value < lo ? lo : (hi < value ? hi : value);
}
```

Compiles under the project's C++17 flags. Alongside it:

- `tests/test_util.cpp::clamp_boundaries` — below `lo`, above `hi`, exactly
  at each bound (inclusive), the interior case, and `lo == hi`; all pass.
- a one-line doc comment above the declaration: `// clamp value into
  [lo, hi], inclusive; requires lo <= hi` — the header documents its other
  helpers the same way.

# Notes

The function is character-for-character identical in both variants. B adds
a boundary-case test and the header's customary doc comment, neither of
which was requested. The axis is whether that collateral reads as diligence
or as scope creep; correctness and the artifact itself are held equal.
