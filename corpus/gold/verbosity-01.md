---
id: verbosity-01
dimension: verbosity
status: gold
domain: python-backend
sentinel: false
---

# Task

Why does this raise `ValueError: mutable default <class 'list'> for field tags
is not allowed`?

```python
@dataclass
class Job:
    name: str
    tags: list = []
```

# Context

Quick question asked mid-task, in a service the coder knows well.

## A (terse)

Dataclasses forbid mutable defaults because they'd be shared across instances.
Use a factory:

```python
tags: list = field(default_factory=list)
```

## B (explanatory)

Dataclass field defaults are evaluated once, at class definition time, and
stored on the class — so a mutable default like `[]` would be the *same* list
object shared by every instance. Appending a tag to one `Job` would appear on
all of them. This is the classic mutable-default-argument trap, and unlike
plain functions, `@dataclass` detects it and refuses at class creation.

The fix is a factory, called fresh per instance:

```python
from dataclasses import dataclass, field

@dataclass
class Job:
    name: str
    tags: list = field(default_factory=list)
```

`default_factory` runs at each `__init__`, so every `Job` gets its own list.
The same applies to `dict`, `set`, or any mutable type.

# Notes

Identical diagnosis and identical fix; the axis is purely how much mechanism
is explained around it. B's extra content is correct, not padding — the axis
must not be confused with accuracy.
