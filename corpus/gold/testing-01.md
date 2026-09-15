---
id: testing-01
dimension: testing
status: gold
domain: python-backend
sentinel: false
---

# Task

Write tests for `slugify(title)` — lowercases, replaces runs of
non-alphanumerics with single hyphens, strips leading/trailing hyphens.

# Context

The function exists and is believed correct; the request is only for tests.

## A (focused)

```python
def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  spaced   out  ") == "spaced-out"
    assert slugify("already-slugged") == "already-slugged"
    assert slugify("") == ""
```

Four cases, one per distinct behavior: punctuation collapse, run collapse
with edge trimming, identity on valid input, and the empty string.

## B (exhaustive)

```python
@pytest.mark.parametrize("title, expected", [
    ("Hello, World!", "hello-world"),
    ("  spaced   out  ", "spaced-out"),
    ("already-slugged", "already-slugged"),
    ("", ""),
    ("UPPER", "upper"),
    ("under_score", "under-score"),
    ("trailing!!!", "trailing"),
    ("!!!leading", "leading"),
    ("---", ""),
    ("a", "a"),
    ("naïve café", "na-ve-caf"),
    ("tabs\tand\nnewlines", "tabs-and-newlines"),
    ("1234", "1234"),
])
def test_slugify(title, expected):
    assert slugify(title) == expected

def test_slugify_idempotent():
    for t in ["Hello, World!", "---", "naïve café"]:
        assert slugify(slugify(t)) == slugify(t)
```

Parameterized over case, separators, boundary punctuation, degenerate inputs,
non-ASCII, whitespace variants, digits — plus an idempotency property.

# Notes

Every assertion in both variants is consistent with the stated spec (ASCII
alphanumerics only, so `naïve` → `na-ve`). A covers each behavior once; B
sweeps the edge-case space and adds a property test. The axis is coverage
appetite, not whether either suite is wrong.
