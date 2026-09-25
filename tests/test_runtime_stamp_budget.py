"""Negative integrity checks for the timestamp experiment's stack reports."""
import hashlib

import pytest

from probe.runtime_stamp_budget import check_stack_pair
from probe.owner_wait_budget import prior_inputs
from whip.fwraw_relocation_trial import CHECKPOINT


@pytest.mark.parametrize("case", ["functionless", "executable_missing", "one_missing", "different", "object_drift"])
def test_only_functionless_objects_may_lack_matching_stack_reports(tmp_path, case):
    manifest, pins, _ = prior_inputs()
    name = "stock_service" if case == "functionless" else "runtime"
    original = pins[name]
    pair = [tmp_path / n for n in ("object.o", "object-repeat.o")]
    for p in pair:
        p.write_bytes(original.read_bytes())
    if case not in ("functionless", "executable_missing"):
        stack = original.with_suffix(".su")
        assert hashlib.sha256(stack.read_bytes()).hexdigest() == manifest["artifacts_sha256"][str(stack.relative_to(CHECKPOINT))]
        pair[0].with_suffix(".su").write_bytes(original.with_suffix(".su").read_bytes())
        if case != "one_missing":
            pair[1].with_suffix(".su").write_bytes(pair[0].with_suffix(".su").read_bytes())
    if case == "different":
        pair[1].with_suffix(".su").write_text("unmatched report\n")
    if case == "object_drift":
        altered = bytearray(pair[1].read_bytes())
        altered[-1] ^= 1
        pair[1].write_bytes(altered)
    if case == "functionless":
        assert check_stack_pair(pair) is False
    else:
        with pytest.raises(ValueError, match={
            "executable_missing": "executable object is missing",
            "one_missing": "presence differs", "different": "report compilation",
            "object_drift": "object compilation",
        }[case]):
            check_stack_pair(pair)
