"""Scratch-only structural study. No firmware linking, device or source edits."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys

from elftools.elf.elffile import ELFFile
from probe.owner_wait_budget import prior_inputs
from whip.fwproof_guard import InputSnapshot

ROOT = Path("/Users/akashanand/Claude_Whip")
HERE = Path(__file__).parent
manifest, pins, previous = prior_inputs()
units = ("adapter", "dispatch")
paths = {str(p): p for p in (Path(__file__), previous,
    ROOT / "firmware/unified/build-20260924-raw-ingress-v1/manifest.json")}
for p in (ROOT / "firmware/unified").glob("*.h"):
    paths[str(p)] = p
for unit in units:
    for p in (ROOT / f"firmware/unified/{unit}.c", HERE / f"{unit}.c", pins[unit]):
        paths[str(p)] = p
inputs = InputSnapshot(paths)
tools = InputSnapshot({"clang": Path(shutil.which("clang")), "python": Path(sys.executable)})
assert tools.hashes == {k: manifest["tool_executables_sha256"][k] for k in tools.hashes}
artifacts = []

def verify():
    for s in (inputs, tools, *artifacts):
        s.verify()

def snapshot(p):
    artifacts.append(InputSnapshot({p.name: p}))

def inventory(raw):
    e = ELFFile(BytesIO(raw))
    functions = {s.name: s["st_size"] for s in e.get_section_by_name(".symtab").iter_symbols()
                 if s["st_info"]["type"] == "STT_FUNC"}
    public = sorted(s.name for s in e.get_section_by_name(".symtab").iter_symbols()
                    if s["st_info"]["type"] == "STT_FUNC" and s["st_info"]["bind"] == "STB_GLOBAL")
    text = sum(s["sh_size"] for s in e.iter_sections() if s.name == ".text" or s.name.startswith(".text."))
    unwind = sum(s["sh_size"] for s in e.iter_sections() if s.name.startswith((".ARM.exidx", ".ARM.extab")))
    writable = sum(s["sh_size"] for s in e.iter_sections() if s["sh_flags"] & 1)
    return dict(text=text, unwind=unwind, writable=writable, functions=functions, public=public)

report = {"limits": "Input object cost only. SCRATCH UNVALIDATED, no ELF, no fit or semantic-proof claim.",
          "units": {}}
for unit in units:
    baseline = inventory(pins[unit].read_bytes())
    for suffix, source in (("baseline", ROOT / f"firmware/unified/{unit}.c"),
                           ("candidate", HERE / f"{unit}.c"), ("repeat", HERE / f"{unit}.c")):
        verify()
        obj = HERE / f"{unit}-{suffix}.o"
        command = [shutil.which("clang"), *manifest["flags"], "-c", str(source), "-o", str(obj)]
        result = subprocess.run(command, capture_output=True, text=True)
        for p in (obj, obj.with_suffix(".su")):
            snapshot(p)
        log = HERE / f"{unit}-{suffix}-command.json"
        log.write_text(json.dumps(dict(command=command, exit=result.returncode,
                                       stdout=result.stdout, stderr=result.stderr), indent=2) + "\n")
        snapshot(log)
        assert result.returncode == 0
    assert (HERE / f"{unit}-baseline.o").read_bytes() == pins[unit].read_bytes()
    assert (HERE / f"{unit}-candidate.o").read_bytes() == (HERE / f"{unit}-repeat.o").read_bytes()
    assert (HERE / f"{unit}-candidate.su").read_bytes() == (HERE / f"{unit}-repeat.su").read_bytes()
    candidate = inventory((HERE / f"{unit}-candidate.o").read_bytes())
    assert candidate["public"] == baseline["public"] and candidate["writable"] == baseline["writable"] == 0
    stacks = {}
    for variant in ("baseline", "candidate"):
        stacks[variant] = {}
        for line in (HERE / f"{unit}-{variant}.su").read_text().splitlines():
            label, size, kind = line.split("\t")
            assert kind == "static"
            stacks[variant][label.rsplit(":", 1)[-1]] = int(size)
    report["units"][unit] = dict(baseline=baseline, candidate=candidate, stack=stacks,
                                text_saved=baseline["text"] - candidate["text"])
report["text_saved"] = sum(r["text_saved"] for r in report["units"].values())
report["whole25_input_lower_bound"] = 10610 - report["text_saved"]
report["whole25_minimum_excess"] = report["whole25_input_lower_bound"] - 9520
report["inputs_sha256"], report["tools_sha256"] = inputs.hashes, tools.hashes
report["artifacts_sha256"] = {k: v for s in artifacts for k, v in s.hashes.items()}
verify()
path = HERE / "structural-report.json"
path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
snapshot(path)
verify()
print(json.dumps({k:report[k] for k in ("text_saved", "whole25_input_lower_bound", "whole25_minimum_excess")}))
for n,r in report["units"].items():
    print(n, "text", r["baseline"]["text"], r["candidate"]["text"], "unwind", r["baseline"]["unwind"],r["candidate"]["unwind"])
