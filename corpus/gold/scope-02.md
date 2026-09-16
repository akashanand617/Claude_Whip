---
id: scope-02
dimension: scope
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

Fix the unchecked return value of `write()` in `ble_send_frame` — a failed
send currently looks like success.

# Context

A ~400-line C++17 module in the ring daemon that drives the BLE bridge over a
serial descriptor. The same function also calls `tcflush()` before the write
and `tcdrain()` after it, both equally unchecked; nobody mentioned those. The
file's error convention is `log_err` with `strerror(errno)` and a `false`
return.

## A (minimal)

The return value was dropped. Checked, in the file's existing style:

```cpp
-    write(fd_, frame.data(), frame.size());
+    if (write(fd_, frame.data(), frame.size()) < 0) {
+        log_err("ble send: write: %s", strerror(errno));
+        return false;
+    }
```

A failed send now logs the errno and reports `false` to the caller like the
rest of the file.

## B (opportunistic)

The return value was dropped. Checked, and while in the function I gave the
two adjacent calls with the same flaw the same treatment, with the log
messages aligned to one format:

```cpp
-    tcflush(fd_, TCIFLUSH);
-    write(fd_, frame.data(), frame.size());
-    tcdrain(fd_);
+    if (tcflush(fd_, TCIFLUSH) < 0) {
+        log_err("ble send: tcflush: %s", strerror(errno));
+        return false;
+    }
+    if (write(fd_, frame.data(), frame.size()) < 0) {
+        log_err("ble send: write: %s", strerror(errno));
+        return false;
+    }
+    if (tcdrain(fd_) < 0) {
+        log_err("ble send: tcdrain: %s", strerror(errno));
+        return false;
+    }
```

All three now fail loudly instead of only the one that was reported.

# Notes

The requested `write()` check is byte-identical in both variants, and both
follow the file's existing error convention. B's two extra checks are real
latent bugs fixed correctly, and entirely unrequested — the axis is whether
that adjacent cleanup is welcome. Neither variant changes behavior on a
healthy link.
