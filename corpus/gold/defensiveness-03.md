---
id: defensiveness-03
dimension: defensiveness
status: gold
domain: web-backend
sentinel: false
---

# Task

Add the internal `/admin/requeue` endpoint: takes `job_id` and `priority`
query params and requeues the job.

# Context

A Flask service. The endpoint sits behind the admin proxy and is called only
by the team's own tooling. Valid priorities are 0-9. `queue.requeue(job_id,
priority)` already exists.

## A (trusting)

```python
@app.post("/admin/requeue")
def requeue():
    job_id = int(request.args["job_id"])
    priority = int(request.args["priority"])
    queue.requeue(job_id, priority)
    return {"requeued": job_id, "priority": priority}
```

Internal tooling: a missing or non-numeric param 500s, and the traceback in
the server log names exactly which line and which param.

## B (defensive)

```python
@app.post("/admin/requeue")
def requeue():
    job_id = request.args.get("job_id")
    if job_id is None or not job_id.isdigit():
        return {"error": "job_id must be a non-negative integer"}, 400
    raw = request.args.get("priority")
    if raw is None or not raw.lstrip("-").isdigit():
        return {"error": "priority must be an integer"}, 400
    priority = max(0, min(int(raw), 9))
    queue.requeue(int(job_id), priority)
    return {"requeued": int(job_id), "priority": priority}
```

Every bad call gets a 400 naming the offending param; out-of-range priorities
are clamped into 0-9 instead of reaching the queue.

# Notes

For any valid call (numeric `job_id`, priority already in 0-9) the two
requeue the same job at the same priority and return the same body. The axis
is only how garbage surfaces: a 500 with a traceback in the log versus
specific 400s and a clamp. Neither swallows the failure -- A's traceback and
B's 400 body both identify the bad input.
