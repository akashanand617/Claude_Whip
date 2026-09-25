# Aborted consolidated ROM read — 2026-09-23

Exact transcript copied from `data/rom-integration-20260923-01/`, unchanged.
SHA-256: `765c09ae673b7b1e2e2839faae61ca722a50ff9ecb7ab53ccd83515c3537e636`.

The freshly coordinated fixed plan sent 189 CD01 requests and received 188
matching diagnostic replies. It stopped on an unrelated UART notification at
the request for 14 bytes at `0x4f8e`; no retry or reconnect occurred. Identity,
configuration/idle, repeated bank0 descriptor and repeated ROM identifier checks
had passed. The first ROM window yielded 1302 bytes once, not a complete repeated
window. None of the five new windows passed the planned repeat/postcheck gate.
There is deliberately no successful `rom-integration.json` capture here.

The original reader did not save the foreign notification's type or payload.
It is therefore unknown whether this was background reporting, streaming or
other traffic. Do not infer a cause or ignore the guard. Notification unsubscribe
and connection teardown ran through the existing cleanup path; the process
exited, but this older abort log did not record the backend's disconnected state.
Do not retroactively claim verified disconnect. Later logging improvements do
not change the content or limitations of this historical transcript.

No sensor, flash, reset, key-field, MMIO or FIFO command was sent. CD01's known
bookkeeping side effects remain. Partial bytes may guide offline investigation,
but do not qualify ROM behavior, RAM ownership, recovery or firmware installation.

`tests/test_fwrom_integration_archive.py` verifies the immutable transcript and
replays the exact outgoing requests and returned replies to the recorded abort,
injecting only the recorded exception, not an invented foreign packet. It proves
the read cannot complete or retry from that state, not what caused the traffic.
