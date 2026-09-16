---
id: testing-05
dimension: testing
status: gold
domain: ml-training
sentinel: false
---

# Task

Write tests for the windowing function (window 50, stride 6).

# Context

`window(x)` slices an array of shape `(T, 3)` into overlapping windows of 50
samples at stride 6: window `i` is `x[6*i : 6*i + 50]`, the output has shape
`(n, 50, 3)` with `n = (T - 50) // 6 + 1` for `T >= 50` and `n = 0`
otherwise (the tail short of a full window is dropped), and the input dtype
is preserved. The function exists and is believed correct.

## A (focused)

```python
def test_window_nominal_shape():
    x = np.zeros((200, 3))
    assert window(x).shape == (26, 50, 3)   # (200 - 50) // 6 + 1

def test_window_drops_short_tail():
    x = np.arange(53 * 3).reshape(53, 3)
    w = window(x)
    assert w.shape == (1, 50, 3)
    assert np.array_equal(w[0], x[:50])     # samples 50..52 dropped
```

Shape for a nominal length, and the tail-remainder case.

## B (exhaustive)

```python
@pytest.mark.parametrize("length, n", [
    (0, 0), (49, 0),          # shorter than one window
    (50, 1), (55, 1),         # one window until the next stride lands
    (56, 2),                  # first length yielding a second window
    (100, 9), (200, 26),      # (T - 50) // 6 + 1
])
def test_window_count(length, n):
    assert window(np.zeros((length, 3))).shape == (n, 50, 3)

def test_window_content_and_overlap():
    x = np.arange(100 * 3, dtype=np.float32).reshape(100, 3)
    w = window(x)
    for i in range(w.shape[0]):
        assert np.array_equal(w[i], x[6 * i : 6 * i + 50])
    for i in range(w.shape[0] - 1):
        assert np.array_equal(w[i + 1][:44], w[i][6:])  # 44 shared samples

def test_window_preserves_dtype():
    for dt in (np.float32, np.int16):
        assert window(np.zeros((60, 3), dtype=dt)).dtype == dt

def test_window_empty_input():
    assert window(np.zeros((0, 3))).shape == (0, 50, 3)
```

A count grid across the boundary lengths, an exact-content and
consecutive-overlap property, dtype preservation, and the empty input.

# Notes

Every count hand-checked against `n = (T - 50) // 6 + 1`: T=200 -> 26,
T=100 -> 9, T=56 -> 2, T=55 and 50 -> 1, T=53 -> 1 with three samples
dropped, T=49 and below -> 0. The overlap property follows from the slicing
rule: consecutive windows share `50 - 6 = 44` samples, so `w[i+1][:44]`
equals `w[i][6:]` exactly. A checks the formula once plus the lossy-tail
behavior; B pins the boundary lattice, the content, dtype, and the
degenerate input. Both pass against a correct implementation; the axis is
coverage appetite.
