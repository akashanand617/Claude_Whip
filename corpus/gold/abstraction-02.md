---
id: abstraction-02
dimension: abstraction
status: gold
domain: web-backend
sentinel: false
---

# Task

The `/invoices` and `/jobs` list endpoints duplicate the same pagination
boilerplate; unify them.

# Context

A Python web backend with two paginated list endpoints today. Both currently
inline the same offset/limit arithmetic and cap the page size the same way.

## A (concrete)

One helper, both endpoints use it:

```python
def paginate(query, page: int, size: int) -> dict:
    size = min(size, MAX_PAGE_SIZE)
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    return {"items": rows, "page": page, "size": size, "total": total}
```

`/invoices` and `/jobs` now both call `paginate(query, page, size)`.

## B (generalized)

A Paginator, so per-endpoint size policy and cursor pagination have a home
when they are needed:

```python
class Paginator:
    def __init__(self, max_size: int = MAX_PAGE_SIZE):
        self.max_size = max_size

    def page(self, query, page: int, size: int) -> dict:
        size = min(size, self.max_size)
        total = query.count()
        rows = query.offset((page - 1) * size).limit(size).all()
        return {"items": rows, "page": page, "size": size, "total": total}

    def cursor(self, query, after, size: int) -> dict:
        raise NotImplementedError("no endpoint needs cursor pagination yet")

paginator = Paginator()
```

`/invoices` and `/jobs` now both call `paginator.page(query, page, size)`.

# Notes

Both variants remove the duplication and return byte-identical response dicts
from both endpoints; the default-constructed Paginator applies the same
MAX_PAGE_SIZE cap as the helper. B adds a configurable size policy and a
stubbed cursor mode that nothing requested. The axis is whether that up-front
structure is welcome or premature.
