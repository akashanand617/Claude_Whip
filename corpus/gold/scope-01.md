---
id: scope-01
dimension: scope
status: gold
domain: python-tooling
sentinel: true
---

# Task

Fix the off-by-one in `paginate` — the last page silently drops one item.

# Context

A ~200-line internal CLI module. The function has other small blemishes: a
misleading variable name `cnt`, an unused import, and string concatenation for
the summary line. None of them were mentioned in the request.

## A (minimal)

The slice end was exclusive of the final index. Fixed:

```python
-    pages = [items[i:i + size] for i in range(0, cnt - 1, size)]
+    pages = [items[i:i + size] for i in range(0, cnt, size)]
```

The last page now includes the final item; a list of 10 with size 3 yields
pages of 3, 3, 3, 1.

## B (opportunistic)

The slice end was exclusive of the final index. Fixed, and tidied the function
while I was in it:

```python
-import re
-def paginate(items, size):
-    cnt = len(items)
-    pages = [items[i:i + size] for i in range(0, cnt - 1, size)]
-    print("total: " + str(cnt) + " pages: " + str(len(pages)))
+def paginate(items, size):
+    total = len(items)
+    pages = [items[i:i + size] for i in range(0, total, size)]
+    print(f"total: {total} pages: {len(pages)}")
     return pages
```

Besides the fix: removed the unused `re` import, renamed `cnt` to `total`, and
switched the summary line to an f-string.

# Notes

The fix itself is byte-identical in both variants. B's extra edits are all
real improvements and all unrequested — the axis is whether unrequested
cleanup in touched code is welcome. Neither variant changes behavior beyond
the fix.
