.syntax unified
.cpu cortex-m0plus
.thumb

/*
 * OFF-RING source for the RT12COL Gesture-only sensor/lease helpers.
 *
 * The checked-in OTA builder embeds the reviewed final bytes and does not run
 * an assembler.  Each four-byte NOP marker below is replaced by one pinned
 * Thumb BL at build-source generation time.  The labels make those callsites
 * unambiguous when regenerating or auditing the blob.
 *
 * These helpers live in the retired WHO_AM_I=0x48 configuration branch.  The
 * physical RT12COL ring identified as LIS2DW12 (0x44), whose active path is
 * retained.  No code here is connected to a device by this source file.
 */

.equ RAW_STATE, 0x209cd4
.equ RAW_OWNER_STATE, 0x209cf4
.equ LEASE_TICKS, 250          /* 25 callbacks/s -> nominal 10-second lease */

#ifndef GESTURE_CTRL1
#define GESTURE_CTRL1 0x61     /* 200 Hz, LP mode 2 (14-bit) */
#endif

.section .text.rt12_helpers,"ax",%progbits
.global rt12_helpers_begin
.global lis2dw12_gesture_config
.global raw_start_config
.global restore_stock
.global disconnect_restore
.global lease_tick
.global raw_first_entry

.thumb_func
rt12_helpers_begin:
lis2dw12_gesture_config:
    push    {r4, lr}
    ldr     r4, =RAW_STATE
    ldrb    r0, [r4, #1]
    cmp     r0, #4
    bne     1f
    /* CTRL6: BW_FILT=00, FS=01 (+/-4 g). */
    movs    r1, #0x10
    movs    r0, #0x25
config_write_ctrl6:
    nop
    nop
    movs    r1, #GESTURE_CTRL1 /* candidate: 0x61 LP2 or 0x60 LP1 */
    b       2f
1:  movs    r1, #0x32          /* exact stock Health CTRL1 */
2:  movs    r0, #0x20
config_write_ctrl1:
    nop
    nop
    pop     {r4, pc}

.thumb_func
raw_start_config:
    push    {r4, lr}
    ldr     r4, =RAW_STATE
    movs    r0, #0
    strb    r0, [r4, #4]       /* first A1 04 initializes the lease */
    movs    r1, #0x10
    movs    r0, #0x25
start_write_ctrl6:
    nop
    nop
    movs    r1, #GESTURE_CTRL1
    movs    r0, #0x20
start_write_ctrl1:
    nop
    nop
    movs    r0, #0
start_original_producer:
    nop
    nop
    pop     {r4, pc}

/* r0 is the stock raw-timer slot.  This is the common A1-stop, disconnect,
 * and lease-expiry cleanup, so no exit can omit a sensor or hold restore. */
.thumb_func
restore_stock:
    push    {r4, lr}
    mov     r4, r0
    ldr     r1, =RAW_STATE
    movs    r0, #0
    strb    r0, [r1]
    strb    r0, [r1, #1]
    strb    r0, [r1, #4]
    movs    r0, #0x40          /* release candidate's exclusive raw owner */
restore_raw_owner:
    nop
    nop
    mov     r0, r4
restore_timer:
    nop
    nop
    movs    r1, #0x32          /* restore exact stock Health CTRL1 first */
    movs    r0, #0x20
restore_write_ctrl1:
    nop
    nop
    movs    r1, #0x50          /* restore exact stock CTRL6 (+/-4 g, ODR/4) */
    movs    r0, #0x25
restore_write_ctrl6:
    nop
    nop

    /* Match 3B 02 01 00: restore volatile motion state {mode=0,sens=1,arg=0}.
     * The stock setter returns zero only when the mode changed; in that case
     * execute the same follow-up used by the command handler. */
    sub     sp, #8
    mov     r1, sp
    movs    r0, #0
    strb    r0, [r1]
    strb    r0, [r1, #2]
    movs    r0, #1
    strb    r0, [r1, #1]
    mov     r0, sp
restore_motion_setter:
    nop
    nop
    cmp     r0, #0
    bne     3f
    movs    r0, #1
restore_motion_release:
    nop
    nop
3:  add     sp, #8
    pop     {r4, pc}

.thumb_func
disconnect_restore:
    push    {r4, lr}
disconnect_original:
    nop
    nop
    ldr     r4, =RAW_STATE
    ldrb    r0, [r4, #1]
    cmp     r0, #4
    bne     4f
    mov     r0, r4
    adds    r0, #0x10
disconnect_common_restore:
    nop
    nop
4:  pop     {r4, pc}

.thumb_func
lease_tick:
    push    {r4, lr}
    ldr     r4, =RAW_STATE
    ldrb    r0, [r4, #4]
    adds    r0, #1
    strb    r0, [r4, #4]
    cmp     r0, #LEASE_TICKS
    blo     5f
    mov     r0, r4
    adds    r0, #0x10
lease_common_restore:
    nop
    nop
5:  pop     {r4, pc}

/* Called only when the compact A1 gate proved that raw active != 1 or mode !=
 * 4. Reconstruct the complete stock first-entry ownership/state setup before
 * returning to its unchanged timer path. */
.thumb_func
raw_first_entry:
    push    {r4, lr}
    ldr     r0, =RAW_OWNER_STATE
first_owner_release:
    nop
    nop
    movs    r0, #0x40
first_owner_record:
    nop
    nop
    movs    r0, #4
    strb    r0, [r7, #1]
    movs    r0, #1
    strb    r0, [r7]
    pop     {r4, pc}

.global rt12_helpers_end
rt12_helpers_end:
