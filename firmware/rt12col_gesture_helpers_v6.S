.syntax unified
.cpu cortex-m0plus
.thumb

/*
 * OFF-RING source for RT12COL V6.
 *
 * V6 is V4-LP2 plus one sensor-state correction: Gesture writes the exact
 * stock WAKE_UP_THS value with SLEEP_ON cleared (0x41 -> 0x01), and every
 * common exit restores exact stock 0x41. The markers are replaced with pinned
 * Thumb BL instructions by the Python builder. This file performs no I/O.
 */

.equ RAW_STATE, 0x209cd4
.equ LEASE_TICKS, 250

#ifndef GESTURE_CTRL1
#define GESTURE_CTRL1 0x61
#endif

.section .text.rt12_helpers_v6,"ax",%progbits
.global rt12_helpers_v6_begin
.global lis2dw12_gesture_config_v6
.global raw_start_config_v6
.global restore_stock_v6
.global disconnect_restore_v6
.global lease_tick_v6
.global raw_first_entry_v6

.thumb_func
rt12_helpers_v6_begin:
lis2dw12_gesture_config_v6:
    ldr     r0, =RAW_STATE
    ldrb    r0, [r0, #1]
    cmp     r0, #4
    beq     gesture_config_v6
    movs    r1, #0x32          /* exact stock Health CTRL1 */
    movs    r0, #0x20
config_v6_tail_write_stock_ctrl1:
    nop

.thumb_func
raw_start_config_v6:
    push    {r4, lr}
    /* At this unchanged stock callsite r7 is RAW_STATE and r6 is zero. */
    strb    r6, [r7, #4]       /* first A1 04 initializes the lease */
start_v6_gesture_config:
    nop
    nop
    movs    r0, #0
start_v6_original_producer:
    nop
    nop
    pop     {r4, pc}

gesture_config_v6:
    push    {r4, lr}
    /* Disable activity/inactivity auto-sleep before selecting 200 Hz. */
    movs    r1, #0x01          /* stock 0x41 with only SLEEP_ON cleared */
    movs    r0, #0x34
config_v6_write_wake_ths:
    nop
    nop
    movs    r1, #0x10          /* CTRL6: +/-4 g, widest bandwidth */
    movs    r0, #0x25
config_v6_write_ctrl6:
    nop
    nop
    movs    r1, #GESTURE_CTRL1 /* V6 0x61=200 Hz; V7 comparison 0x51=100 Hz */
    movs    r0, #0x20
config_v6_write_ctrl1:
    nop
    nop
    pop     {r4, pc}

/* r0 is the stock raw-timer slot. All explicit/disconnect/lease exits use
 * this one helper, so none can omit the exact stock WAKE_UP_THS restore. */
.thumb_func
restore_stock_v6:
    push    {r4, lr}
    mov     r4, r0
    ldr     r1, =RAW_STATE
    movs    r0, #0
    strh    r0, [r1]           /* clear raw active and mode together */
    strb    r0, [r1, #4]
    movs    r0, #0x40
restore_v6_raw_owner:
    nop
    nop
    mov     r0, r4
restore_v6_timer:
    nop
    nop
    movs    r1, #0x32
    movs    r0, #0x20
restore_v6_write_ctrl1:
    nop
    nop
    movs    r1, #0x50
    movs    r0, #0x25
restore_v6_write_ctrl6:
    nop
    nop
    movs    r1, #0x41          /* exact stock SLEEP_ON + threshold value */
    movs    r0, #0x34
restore_v6_write_wake_ths:
    nop
    nop

    /* Exact byte state for {mode=0, sensitivity=1, arg=0}. */
    sub     sp, #8
    movs    r0, #1
    lsls    r0, r0, #8
    str     r0, [sp]
    mov     r0, sp
restore_v6_motion_setter:
    nop
    nop
    cmp     r0, #0
    bne     3f
    movs    r0, #1
restore_v6_motion_release:
    nop
    nop
3:  add     sp, #8
    pop     {r4, pc}

.thumb_func
disconnect_restore_v6:
    push    {r4, lr}
disconnect_v6_original:
    nop
    nop
    ldr     r4, =RAW_STATE
    ldrb    r0, [r4, #1]
    cmp     r0, #4
    bne     4f
    mov     r0, r4
    adds    r0, #0x10
disconnect_v6_common_restore:
    nop
    nop
4:  pop     {r4, pc}

.thumb_func
lease_tick_v6:
    push    {r4, lr}
    ldr     r4, =RAW_STATE
    ldrb    r0, [r4, #4]
    adds    r0, #1
    strb    r0, [r4, #4]
    cmp     r0, #LEASE_TICKS
    blo     5f
    mov     r0, r4
    adds    r0, #0x10
lease_v6_common_restore:
    nop
    nop
5:  pop     {r4, pc}

.thumb_func
raw_first_entry_v6:
    push    {r4, lr}
    ldr     r0, =RAW_STATE
    adds    r0, #0x20          /* RAW_OWNER_STATE */
first_v6_owner_release:
    nop
    nop
    movs    r0, #0x40
first_v6_owner_record:
    nop
    nop
    movs    r0, #4
    strb    r0, [r7, #1]
    movs    r0, #1
    strb    r0, [r7]
    pop     {r4, pc}

.global rt12_helpers_v6_end
rt12_helpers_v6_end:
