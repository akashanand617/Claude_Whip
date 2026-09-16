---
id: testing-03
dimension: testing
status: gold
domain: python-tooling
sentinel: false
---

# Task

Write tests for `parse_duration` ('1h30m' -> 5400).

# Context

`parse_duration(s)` returns total seconds as an int. Input is one or more
`<integer><unit>` components with unit in `h`, `m`, `s` (lowercase), each
unit at most once, in any order; components may be separated by spaces and
surrounding whitespace is ignored. Anything else -- empty string, missing
unit, unknown unit, repeated unit, non-integer count -- raises
`ValueError("invalid duration: ...")`. The function exists and is believed
correct; the request is only for tests.

## A (focused)

```python
def test_parse_duration():
    assert parse_duration("1h30m") == 5400
    assert parse_duration("45s") == 45
    assert parse_duration("0s") == 0
    with pytest.raises(ValueError):
        parse_duration("1x")
```

Four cases: a composite, a single unit, zero, and one malformed input.

## B (exhaustive)

```python
@pytest.mark.parametrize("s, expected", [
    ("1h30m", 5400),
    ("30m1h", 5400),        # order is free
    ("1h1m1s", 3661),
    ("2h", 7200),
    ("90m", 5400),          # values may exceed the next unit up
    ("45s", 45),
    ("0s", 0),
    ("1h 30m", 5400),       # spaces between components
    ("  1h30m  ", 5400),    # surrounding whitespace
    ("10000h", 36000000),   # large values don't wrap
])
def test_parse_duration(s, expected):
    assert parse_duration(s) == expected

@pytest.mark.parametrize("bad", [
    "", "h", "90", "1x", "1h1h", "1.5h", "m30",
])
def test_parse_duration_rejects(bad):
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration(bad)
```

A grid over unit combinations, ordering, whitespace variants, and magnitude,
plus a table of malformed inputs each asserting the error message.

# Notes

Every expected value hand-checked against the spec: 1h30m = 3600 + 1800 =
5400; 1h1m1s = 3661; 90m = 5400; 10000h = 36,000,000; reordering and
whitespace are legal per the stated grammar, and each entry in the malformed
table violates exactly one stated rule (empty, missing count, missing unit,
unknown unit, repeated unit, non-integer, count after unit). A covers each
distinct behavior once; B sweeps the input space and pins the error message.
Both suites pass against a correct implementation; the axis is coverage
appetite.
