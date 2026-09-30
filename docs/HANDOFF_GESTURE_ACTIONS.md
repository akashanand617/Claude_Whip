# Handoff — iOS gesture actions (2026-09-29)

All work below is **uncommitted** in the working tree of `/Users/akashanand/Claude_Whip`.
Other Claude sessions also edit this repo; check `git status` before committing.

## What exists

The ring's on-phone gesture CNN now drives real phone actions.

- **Actions**:
  - Apple Music: next, previous, play/pause, restart, shuffle, repeat.
  - Pause gestures (return to Health).
  - Research labels: Flag / Approve / Mark.
  - Ping phone (a local notification).
  - Swipe up/down: present but **locked** (does nothing).
- **Defaults**:

  | Gesture | Action |
  |---|---|
  | flick_right | Next track |
  | flick_left | Previous track |
  | flick_up / flick_down | Swipe up / down (locked) |
  | snap | Pause gestures |
  | others | none |

  Tap a cell in the Gestures tab to remap.
- **Back Tap**:
  - App Intents: Toggle, Start, and "Pause Gestures (Return to Health)".
  - Shortcuts lists them under "R02Ring". The user builds a shortcut and assigns it in Settings › Accessibility › Touch › Back Tap; a setup sheet is in the Gestures tab.
  - Start/Toggle wait up to 8 s for calibration and reply "Gestures ready ✓". Otherwise a single "Gestures ready ✓" notification follows.
- **Sticky sessions**:
  - A session ends only for: user/intent stop, the pause gesture, the user's session or idle timer, charging, the ring gone for more than 60 s, or the heal giving up.
  - Stalls, renewal misses, lease lapses and reconnects heal back into Gesture.
  - Recognition is paused while healing; stale data never drives an action.
  - Policy table: `Model/GestureSessionPolicy.swift`.
  - Heal loop: `Model/GestureSessionKeeper.swift`.
- **Background**: sessions keep running while R02 is backgrounded (setting, default on). Idle auto-pause defaults to 15 min.
- **Ring writes**: only the audited packets: A1 04 / A1 05 / A1 02 / 3B 02 01 03 / 3B 02 01 00.
- **Logs on the phone** (`Documents/GestureEvents/`):
  - `events_*.jsonl`: Python EventLog schema, joinable with `python -m probe.label join`.
  - `lifecycle_YYYYMMDD.jsonl`: the session journal (stream stats, renewals, heals, stale details, calibration).

  Pull them with:
  ```
  DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun devicectl device copy from \
    --device 00008110-001201E03AF9A01E --domain-type appDataContainer \
    --domain-identifier com.abhayanand.R02Ring \
    --source Documents/GestureEvents/<file> --destination <local>
  ```

## Verification status

- **XCTest**: 382 tests pass, 0 failures, no skips. Run on the cloned simulator `Whip-Actions-18Pro` (`16398E1C-34E6-4BEE-B74D-628E24AACBCF`).
  ```
  DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild test \
    -project ios/R02Ring.xcodeproj -scheme R02Ring \
    -destination 'platform=iOS Simulator,id=16398E1C-34E6-4BEE-B74D-628E24AACBCF' CODE_SIGNING_ALLOWED=NO
  ```
- **Release**: the simulator build succeeds.
- **Python**: `tests/test_labeling.py` and `tests/test_ios_event_log_contract.py` pass.
- **Physical, first round** (iPhone 14 + RT12COL V7, before the latest fixes):
  - Back Tap from other apps and background Apple Music control worked.
  - Sessions ended early. Diagnosed as the renewal timing gate being too tight for the phone's ~30 ms BLE connection grid, plus brief stalls tripping 0.25 s freshness checks.
- **Not yet tested on the phone**: the fixes for those problems (renewal gate, stall tolerance, sticky heal, ready confirmation).

## Next steps

1. Rebuild to the iPhone from Xcode.
2. Test: Back Tap from Music/Instagram; "Gestures ready ✓"; flicks; snap pause; sessions staying on.
3. Pull the journal and check:
   - `renewal` records (mean_ms 24–64, max_ms ≤ 500);
   - `heal_*` records;
   - `stale_detail` records;
   - `main_stall` / `stream_stall` records.

## Known open items

- If iOS kills R02 and never relaunches it, the session end is only reported at the next launch.
- A stream that repeatedly stalls and heals is never ended; only the 180 s cap on a single heal attempt bounds it.
- Lease-less firmware still ends the session immediately instead of healing.
- Charging is only re-checked at start or heal, not mid-segment.
- There is no AppModel-level integration test harness; the logic is tested through extracted pure types.
- Swipe up/down remain locked. They were not implemented in the previous session.

## Detailed records

- `ios/IMPLEMENTATION.md`: dated 2026-09-28/29 sections with the feasibility table, diagnosis, and review corrections.
- `AGENTS.md` / `CLAUDE.md`: 2026-09-28 section.
- Approved plan: `~/.claude/plans/warm-growing-cherny.md`.
