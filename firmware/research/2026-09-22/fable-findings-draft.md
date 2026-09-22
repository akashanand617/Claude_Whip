# LED / optical front end in RT02CR firmware -- analysis findings (draft for verification)

Image analysed: `firmware/rt02cr-25hz.bin` (137540 bytes; the image currently flashed).
All addresses below are FILE offsets unless marked `abs`. abs = file - 0x450 + 0x826400.

## Tooling (scratchpad)

- `fwmap.py` -- annotated function map. `python fwmap.py func 0xOFF`, `xref 0xOFF`, `grep REGEX`, `calls SYMBOL`, `str`.
  Output listing: `fw/listing.txt` (every function, annotated: bl targets named, literal pools resolved,
  ROM symbols from `rom_symbol_gcc.axf` (RTL8762E ROM), peripherals named). `fw/functions.json`.
- Run with the project venv: `/Users/akashanand/Claude_Whip/.venv/bin/python <scratchpad>/fwmap.py ...`

## Platform facts (established this session)

- SoC is a Realtek RTL8762E-family (Bee3, Cortex-M0+), NOT BlueX RF03 as CLAUDE.md says. Evidence: 79 distinct
  BL targets into ROM (< 0x100000) all match the RTL8762E SDK ROM symbol table once the Thumb bit is added
  (os_timer_create 0x13634, os_timer_stop 0x136bc, memcpy 0x3f848, log_buffer 0x5aa8, os_mutex_take 0x133f4 ...).
- App image load base: file 0x450 <-> abs 0x00826400. Evidence: entry vector at 0x450 is `ldr r0,[pc]; bx r0; .word 0x00826665`;
  Realtek header words 0x00826400 at file 0x6c/0x70; brute-force scan: 56 of 80 odd flash literals land on `push {..,lr}`
  at this base, next best base scores 13.
- .data copy table in reset handler sub_006b4 (file 0x768): flash 0x846a98 -> RAM 0x207c00 (0x8b0 bytes) = file 0x20ae8..0x21398;
  flash 0x847348 -> RAM 0x2084b0 (0x4e4 bytes, RAM-resident code) = file 0x21398..0x2187c; bss 0x208994 +0x5d80.
- I2C0 @0x40015000 on P2_4/P2_5 (Pinmux funcs 5/6), init in sub_0d750. VC30F optical AFE at 7-bit addr 0x33
  (sub_0ecaa = vc30f_read(reg,buf,len), sub_0ece2 = vc30f_write(reg,buf,len), both `movs r0,#0x33` then sub_0dc66/sub_0db62).
  VC30F INT on P4_1 (pad 33, sub_0d7d8). Accelerometer INT on P2_6 (pad 22, sub_0ba44; ISR sub_0bb12).
  Accelerometer driver: sub_0c112/sub_0c1bc probe several chip IDs (0x23 = STK8321 -> sub_0bef8 init).
  No pad is configured as an output that could be a sensor power/enable pin (Pad_Config survey: only P4_0 (32, charger detect GPIO),
  P2_7 (23, ADC), I2C pins, INT pins).
- VC30F driver library string "core30fx_v0.23" at 0x1f65c (referenced by sub_1157c). Chip IDs accepted 0x25 / 0x27 (sub_0f636, sub_10016).

## Command flow for `A1 xx` (raw sensor)

1. BLE packet dispatcher sub_0564a: `cmp r0,#0xa1` at 0x56f4 -> 0x56b6 -> 0x59c0 -> sub_04b9c(packet) = enqueue 16-byte packet
   into ring queue at RAM 0x209d48 and post message 0x332 (sub_01178).
2. Task-side dispatcher sub_06334 (caller sub_01316): `cmp r1,#0xa1` at 0x6394 -> 0x6440 -> **sub_020bc(packet) = A1 handler**.
3. sub_020bc (file 0x20bc, 570 bytes). First `bl sub_02d4e` = charging flag (bit0 of RAM 0x209ce4, set by charger module sub_02d5c);
   if charging -> reply `A1 FF` and return. Then switch on packet[1]:
   - 0x01 (0x211e): save stats; sub_0deb6(); **sub_0dc82(0xffff)** (disable all sensor bits); **sub_0dc9c(0x40)** (enable bit 0x40);
     sub_1475c(0x64,0x2710); mode byte [0x209cac]=1; -> 0x2246 start producer timer.
   - 0x02 (0x2190): restore stats; **sub_0dc82(0x40)**; sub_0d746(); [0x209cac]=0; sub_03d38(&timer 0x209cbc) = stop+delete timer.
     NOTE: does NOT disable bit 0x800.
   - 0x03: -> 0x22ee (just calls sub_01dfe(0) once = one-shot report).
   - **0x04 (0x21d6): sub_0dc82(0xffff); sub_0dc9c(0x800); mode=4; -> 0x2246 start producer timer.**
   - **0x05 (0x21e8): sub_0dc82(0x800); mode=0; sub_03d38(timer) stop.**  <- the matching STOP for 0x04.
   - 0x06 (0x21fc): like 0x01 (bit 0x40) with mode=6.
   - 0x07 (0x2258): if mode==0: sub_0dc9c(0x40) and timer at 0x7d<<3 = 1000 ms; sets [0x209cad]=1 and a countdown from packet[2..3].
   - 0x08 (0x2298): sub_0dc82(0x40); stop timer; reply with counters.
   - Producer timer start at 0x2246: sub_03d0c(&0x209cbc, cb=sub_01dfe, period=(4<<3)=32 ms [the #4 immediate at 0x2248], reload=1).
     sub_03d0c = os_timer_create(...,reload)+os_timer_start (or os_timer_restart if handle exists).
4. sub_0dc9c(bits) posts message {3,1,bits} id 0x195; sub_0dc82(bits) posts {3,2,bits} id 0x18d (both via sub_0149c). Handled by
   sub_0dcd0 (caller sub_01400 = task loop): sub 1 -> **sub_0f68c(bits) = sensor_enable**, sub 2 -> **sub_0f740(bits) = sensor_disable**,
   sub 0 -> sub_0f616, sub 3 -> sub_0f798 (nop).

## Bit usage (who enables which bits) -- extracted from every call site

ENABLE sub_0dc9c: sub_020bc: 0x40 (x3), 0x800; sub_0441c: 0x38; sub_050dc: 0x1, 0xff, 0x200, 0x1000, 0x20, 0x1; sub_0a672: 0x1;
sub_0ddd0: 0x2; sub_0e0a4: 0x80; sub_0e35c: 0x10; sub_0e452: 0x10; sub_0e7f2: 0x200; sub_0e988: 0xff; sub_0ebee: 0x1000.
=> **bits 0x40 and 0x800 are used ONLY by the A1 raw handler.** No other feature depends on them.

## sensor_enable sub_0f68c(bits) (file 0xf68c)

```
mask = u16 [0x20c018]; r7 = bits & 0xa0
if mask != 0:
    if mask & 0x40: mask |= bits; return                       (0xf6aa..)
    if (bits & 0xa0) && !(mask & 0xa0): reconfigure: cfg.rate=0x190, cfg.mode=1; sub_19018; sub_14760; sub_0eff8(cfg); ...
    mask |= bits; return
else (mask == 0):
    if !sub_0f636(): [0x20c01b]=1; [0x20c01c]=3; return         (VC30F chip-ID probe failed -> give up)
    if bits & 0xa0: cfg.rate=0x190 (400), cfg.mode=1
    elif bits == 0x40 or bits == 0x800: cfg.rate=0xc8 (200), cfg.mode=7      <- 0xf702..0xf71a  (RAW MODE)
    else: cfg.rate=0xc8, cfg.mode=0
    sub_19018(); sub_14760(); sub_0eff8(cfg)   <- starts the VC30F
    [0x20c01c]=1 (running); [0x20c01a]=0; u16[0x20c01e]=0
    mask |= bits; return                                        (0xf6d8)
```
cfg struct at RAM 0x208548: u16 rate at +0, u8 mode at +2.

## sensor_disable sub_0f740(bits) (file 0xf740)

```
if [0x20c008] (VC30F absent flag): return
mask &= ~bits
if mask == 0: sub_10d12(0) [VC30F stop]; [0x20c109]=0; [0x20c01c]=0; [0x20c10a]=0; return
if !(bits & 0xa0) or (mask & 0xa0): return
sub_10d12(0); [0x20c109]=0; if [0x20c01c]==2: [0x20c01c]=1; cfg.mode=0; sub_0eff8(cfg)   (restart without wear-detect slot)
```

## VC30F start path

sub_0eff8(cfg) (file 0xeff8): switch on cfg.mode via jump table -> picks sample rate r6 (25/50/100) and params; calls
**sub_10c86(0x20854c, mode, ...)** which looks the mode up in a table at file 0x1f5e4 (entries {mode, fn_a, fn_b}, 10 entries) and calls
**sub_10016(...)**: checks chip ID 0x25/0x27; sub_112c0; sub_122fe(2) [reg 0x7b <- 0xa5]; sub_1135c; `blx fn_a` (mode-specific slot/LED setup);
sub_0fb0a; reads reg 0x40 (24 bytes); sub_12094 (reg 0x51 <- cfg+0x16, cfg+0x17); **sub_122fe(1) [reg 0x7b <- 0x5a = run]**.

Mode table (file 0x1f5e4): mode 0/2/3 -> sub_0fd36 (slot0 green LED current 0x40 + slot2 env), 1 -> sub_0fd96 (slot0 0x40, slot1 0x40, slot2),
4 -> sub_0fe2a, 5 -> sub_0fe8a (slot2 only), 6 -> sub_0ffd8 (slot2 only), **7 -> sub_0fec4 (slot0 current 0x7f, slot1 current 0x7f, slot2; sub_11200; sub_1121c(0xe))**,
8 -> sub_0ff4e (same as 7), 10 -> 0x10012 (nop).
Slot LED current literals in sub_0fec4: `movs r2,#0x7f` at 0xfee0 (slot0) and 0xff04 (slot1); slot2 current 0xb at 0xfee6 (`movs r6,#0xb`).
Slot setup helpers: sub_0f8ec (slot0), sub_0f93e (slot1), sub_0f98c (slot2) -> sub_111f0/sub_111f8/sub_111dc/sub_111d4 -> register writes.
VC30F stop: sub_10d12 = sub_122fe(2) then sub_122fe(0): reg 0x7b <- 0xa5, then 0x00.
VC30F register writes used by the driver (reg numbers): 0x40 (24-byte config block), 0x42, 0x46, 0x48, 0x49, 0x4a, 0x4c, 0x4d(4B), 0x4f, 0x51, 0x52,
0x53, 0x54, 0x55, 0x57, 0x7b, 0xfe/0xff, 0x0b(4B), 0x03; reads 0x00 (ID), 0x02, 0x06.

## Producer timer callback sub_01dfe (file 0x1dfe, every 32 ms)

Builds and sends (sub_07c0c = BLE notify) in order:
- `A1 01` spo2 frame from sub_0ded6() = u32 [0x20c060] and globals 0x2089e8/ec/f0 -- send call at 0x1e58 is NOP'd (upstream patch).
- `A1 02` ppg frame from sub_0dece() = u32 [0x20c098] -- send at 0x1eb2 NOP'd.
- **`A1 03` accel frame: sub_0cbda(&x,&y,&z,1) then sub_07c0c at 0x1f32 -- ALWAYS sent.**
- `A1 05` frame from sub_0df44() = u16 [0x20c012] (wear state) -- send at 0x1f74 NOP'd.
Then: if sub_02d4e() (charging): disable 0x40, stop timer. Mode 4 (`[0x209cac]==4`): sub_1475c(0x64,0x1f4) and return.
Modes 1/6/7 have auto-stop logic that disables 0x40.

sub_0cbda(x,y,z,n) reads the newest n samples from the accelerometer ring buffer at RAM 0x20bdc4+0xc (6-byte LE XYZ entries, write index u16 at +8);
if flag [0x20bdc5] is set it first calls sub_0c228 (drain STK8321 FIFO over I2C into the ring buffer). The ring buffer is filled by the
accelerometer interrupt path: ISR sub_0bb12 (P2_6) -> sub_0cf4c/sub_0cf4e (set flags, post msg 0x7c3) -> sub_0cfc6 -> sub_0ca60 -> sub_0c228 (+ step algo).
Also read by sub_0ed20 (VC30F sample processing) -- a second consumer, not a producer.
=> **The accelerometer data path does not depend on the VC30F being started.**

## ROOT CAUSE of "LEDs on during tracking and stuck on afterwards"

1. `A1 04` -> sub_0f68c(0x800) -> mode 7 -> VC30F started with green+red LEDs at max current (0x7f). That is the flicker during tracking.
2. `A1 02` only disables bit 0x40. After `A1 04` the mask still holds 0x800, so the VC30F keeps running -> LEDs stay on until a power cycle.
   **The correct stop for `A1 04` is `A1 05`** (disables 0x800 -> mask 0 -> sub_10d12 -> VC30F stopped). Never sent by this project or upstream.

## Proposed fixes

### Fix A (protocol only, works on the flashed firmware today)
Send `A1 05` (packet a1 05 00.. checksum 0xa6) to stop raw mode 4. LEDs should go off without a charger tap.
Keep `A1 02` as well (harmless, clears 0x40 for the PPG modes). Expected: no change to LEDs *during* streaming.

### Fix B (firmware patch, one halfword) -- `rt02cr-25hz-noled.bin` (built in scratchpad, sha256 3c57b73e...)
REVISED TARGET: File 0xf710: `51 48` (`ldr r0,[pc,#0x144]`, start of the mode-7 config) -> `e5 e7` (`b #0xf6de` = the function's `pop`,
NOT the `orrs` at 0xf6d8). Effect: in sensor_enable, when mask==0 and bits==0x40 or bits==0x800 (both raw-mode bits, used only by A1), skip
the VC30F configuration/start entirely AND leave the mask at 0 (the raw bit is not recorded). The VC30F stays in its stopped state
(reg 0x7b = 0x00, as left by the preceding sub_0dc82(0xffff)).
Why the mask must stay 0: the minute tick sub_01202 (caller sub_01316) runs the hourly health schedule while [0x208c4a]==1: at minute 32
sub_0e0a4 -> enable 0x80 (wear detect), at minute 0 sub_0e988 -> enable 0xff, plus sub_0e35c/sub_0e7f2/sub_0ebee (0x10/0x200/0x1000).
With 0x800 left in the mask (old target 0xf6d8, and also the UNPATCHED firmware today), sub_0f68c's mask!=0 branch would start the VC30F in
mode 1 for the wear check, and sub_0f740(0x80) at its end would find mask==0x800 != 0 and RESTART the VC30F in mode 0 (0xf786..0xf78c) --
LEDs on and stuck. With mask==0 the schedule behaves exactly as at idle (brief measurement, then sub_10d12 stop). `16 02 02 3c`
(DISABLE_LOGGING) suppresses the schedule on either firmware.
Old candidate (target 0xf6d8, bytes e2 e7, sha 2e2045c1...) is superseded; the verifiers' checks of the mechanics still apply.
The 32 ms producer timer still runs; `A1 03` accel frames still come from the accelerometer ring buffer.
Side effects: `A1 01/06/07` (PPG raw streaming, bit 0x40) would also stream without the optical sensor (stale PPG values). Nothing else uses these bits.
State byte [0x20c01c] is not set to 1 in the patched path (normal path sets it after start). Readers of the sensor state struct: sub_0e3b6, sub_0f172,
sub_0f1c2 (x9), sub_0f5a6..sub_0f5d2, sub_0f624, sub_0f68c, sub_0f740, sub_0f792, sub_0f79a -- VERIFY none of these is reached in raw mode in a way that matters.
Stopping later with `A1 05` -> sub_0f740(0x800) -> mask 0 -> sub_10d12 writes reg 0x7b (harmless on an already-stopped chip) -- VERIFY.
With `A1 02` (the current stop) the mask keeps 0x800 but nothing is running, so no LED and no extra power -- but the next `A1 04` does
sub_0dc82(0xffff) first, so the stale bit is cleared anyway.

Alternative B' (not chosen): zero the LED currents in sub_0fec4 (0xfee0/0xff04 `movs r2,#0x7f` -> `#0`) and keep the VC30F running: the AFE and
the sample interrupts stay on (battery), the AGC (sub_0fa8e/sub_0fc02 adjusting current via sub_11240) may raise the current again, and slot 2 (0xb)
still pulses an LED. Fix B removes the whole optical front end from raw mode instead.

## Open questions for verifiers
1. Is the reading of sub_020bc case 0x02 vs 0x05 correct (0x40 vs 0x800)? Check bytes at 0x21be..0x21c4 and 0x21e8..0x21ee.
2. Does anything in raw mode 4 (mode byte 4 at 0x209cac) require the VC30F to be running or [0x20c01c]==1? (producer sub_01dfe, sub_0f1c2 path, wear detection)
3. Is `b #0xf6d8` at 0xf710 the right target (mask |= bits; pop) and is the encoding e2e7 correct for a Thumb B with offset -30 halfwords? Check that
   0xf6d8 is not inside a literal pool and that nothing branches INTO 0xf712..0xf71a expecting r0 loaded.
4. Are bits 0x40/0x800 really only enabled from sub_020bc? (re-derive from listing; also check `sub_0dc9c` callers with register args)
5. Battery: which consumer dominates? If the VC30F is off, expected remaining drain = BLE connection + MCU + accel. Any hint in the image of
   power-mode changes tied to raw mode (platform_pm_set_power_mode calls, sub_1475c(0x64,...) meaning)?
6. Is there any other path that turns the VC30F on while streaming (e.g. periodic wear detection timers enabling 0x80/0x20 -> mask!=0 path -> since
   mask has 0x800 (nonzero) and !(mask & 0x40), bits&0xa0 -> reconfigure with mode 1 -> VC30F started with LEDs)? In the UNPATCHED firmware this
   also happens today. Check what enables 0x80 (sub_0e0a4) / 0x20 (sub_050dc) and when.
