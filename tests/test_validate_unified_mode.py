import asyncio
import io

import pytest

from probe import validate_unified_mode as validation
from whip import fwidentity, protocol


class HealthClient:
    def __init__(self, readings=(), fail_start=False):
        self.readings = readings
        self.fail_start = fail_start
        self.writes = []
        self.notify_stopped = False

    async def start_notify(self, _uuid, callback):
        self.callback = callback

    async def stop_notify(self, _uuid):
        self.notify_stopped = True

    async def write_gatt_char(self, _uuid, packet, response=False):
        packet = bytes(packet)
        self.writes.append(packet)
        if packet == validation.START_HR:
            if self.fail_start:
                raise RuntimeError("start failed")
            self.callback(None, protocol.make_packet(0x69, bytes([1, 0, 0])))
            for bpm in self.readings:
                self.callback(None, protocol.make_packet(0x69, bytes([1, 0, bpm])))


def test_local_unified_and_rollback_artifacts_are_exact():
    base, candidate = validation.validate_local_artifacts()
    assert fwidentity.classify(base, {
        site.name: candidate[site.file_offset:site.file_offset + site.length]
        for site in fwidentity.read_sites()
    }) == fwidentity.UNIFIED_CANDIDATE


def test_health_resume_requires_five_valid_readings_and_always_stops():
    client = HealthClient([71, 72, 73, 74, 75])
    result = asyncio.run(validation.health_resume(client, io.StringIO(), 0.1))
    assert result["passed"] and result["valid_bpm_readings"] == [71, 72, 73, 74, 75]
    assert client.writes == [validation.START_HR, *validation.STOP_HR]
    assert client.notify_stopped


def test_malformed_or_too_few_health_readings_fail_closed():
    client = HealthClient([0, 29, 241, 80])
    result = asyncio.run(validation.health_resume(client, io.StringIO(), 0.001))
    assert not result["passed"]
    assert result["valid_bpm_readings"] == [80]
    assert client.writes[-2:] == list(validation.STOP_HR)


def test_health_start_failure_still_attempts_both_stops():
    client = HealthClient(fail_start=True)
    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(validation.health_resume(client, io.StringIO(), 1))
    assert client.writes == [validation.START_HR, *validation.STOP_HR]
    assert client.notify_stopped


@pytest.mark.parametrize("args", [
    ["--gesture-duration", "nan"], ["--stopped-duration", "9"],
    ["--health-timeout", "inf"], ["--connect-timeout", "0"],
])
def test_cli_rejects_invalid_durations_before_ble(args):
    with pytest.raises(SystemExit) as error:
        validation.main(["--address", "unused", *args])
    assert error.value.code == 2
