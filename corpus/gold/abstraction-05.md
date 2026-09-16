---
id: abstraction-05
dimension: abstraction
status: gold
domain: ml-training
sentinel: false
---

# Task

Both trainers duplicate metric logging; consolidate.

# Context

The gesture trainer and the reward-model trainer each open `metrics.jsonl`
and write the same `{"step": ..., **metrics}` line inline. One shared
implementation should replace both copies.

## A (concrete)

One shared function:

```python
def log_metrics(step: int, metrics: dict,
                path: str = "metrics.jsonl") -> None:
    with open(path, "a") as f:
        f.write(json.dumps({"step": step, **metrics}) + "\n")
```

Both trainers now call `log_metrics(step, metrics)`.

## B (generalized)

A sink interface, so a second backend can be added without touching the
trainers:

```python
class MetricsSink:
    def log(self, step: int, metrics: dict) -> None:
        raise NotImplementedError

class JsonlSink(MetricsSink):
    def __init__(self, path: str = "metrics.jsonl"):
        self.path = path

    def log(self, step: int, metrics: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"step": step, **metrics}) + "\n")

class TensorBoardSink(MetricsSink):
    def log(self, step: int, metrics: dict) -> None:
        raise NotImplementedError("wire up when TB dashboards are wanted")
```

Both trainers take `sink: MetricsSink` and call `self.sink.log(step,
metrics)`; today each is constructed with `JsonlSink()`.

# Notes

Both variants write the byte-identical jsonl line the trainers already write,
to the same default path. B adds an interface, constructor plumbing through
both trainers, and a stub sink for a backend nobody has asked for. The axis
is whether that seam is prudent structure or premature indirection.
