# Direct FEE7 reference survey — NOT A FIRMWARE IMAGE

Root directly inspected the pinned stock binary after the user requested an
independent WeChat check. `audit.py` produces `report.json`; `check_findings.py`
checks its explicit interpretations and produces `findings.json`. Reproduce in
a fresh directory; both scripts refuse to overwrite their output.

No stock, linker, device or production gate was changed. 790 gross candidate
bytes are NOT approved space. Shared callback selectors differ from the setup
ID slot, and a separate startup path advertises FEE7. See the
[audit and limits](../../../docs/UNIFIED_WECHAT_RETIREMENT.md).
