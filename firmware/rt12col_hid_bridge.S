.syntax unified
.cpu cortex-m0plus
.thumb

/*
 * OFF-RING source for the RT12COL UART-to-HID bridge.
 *
 * The exact RT12COL_V1.0 ring uses LIS2DW12 WHO_AM_I 0x44. The builder first
 * retires both calls to the stock STK8321-only initializer, then places this
 * size-neutral bridge in that initializer's 80-byte span.
 *
 * The UART dispatcher has already accepted a checksum-valid 16-byte packet.
 * r0 points at its command byte and r1 contains that byte. Command 0xA2 uses:
 *
 *   action 0..3       stock mouse drag up/down/left/right
 *   action 0x20..0x37 stock Consumer Control descriptor bit 0..23
 *
 * Unknown actions are consumed without emitting HID. Non-0xA2 commands leave
 * r0/r1 intact, except 0x3B: the hook displaced both the stock comparison and
 * its taken branch, so the bridge calls the exact stock 0x3B handler before
 * returning to the dispatcher tail. The NOP pairs are replaced with pinned
 * Thumb BL instructions by the Python builder.
 */

.section .text.rt12_hid_bridge,"ax",%progbits
.global rt12_hid_bridge_begin
.global rt12_hid_bridge

.thumb_func
rt12_hid_bridge_begin:
rt12_hid_bridge:
    push    {r4, lr}
    mov     r4, r0
    cmp     r1, #0xa2
    bne     finish

    ldrb    r0, [r4, #1]
    cmp     r0, #4
    bhs     consumer

    movs    r2, #1              /* stock mouse-drag trajectory */
    cmp     r0, #2
    bhs     horizontal

    movs    r1, #1
    cmp     r0, #0
    bne     vertical_ready       /* 1: down */
    rsbs    r1, r1, #0           /* 0: up */

vertical_ready:
    movs    r0, #0
    b       run_swipe

horizontal:
    movs    r1, #0
    subs    r0, #2
    lsls    r0, r0, #1
    subs    r0, #1              /* 2: left (-1), 3: right (+1) */

run_swipe:
    nop
    nop                         /* stock mouse/touch trajectory scheduler */
    b       handled

consumer:
    subs    r0, #0x20
    cmp     r0, #0x18
    bhs     handled
    nop
    nop                         /* stock one-hot Consumer Control press */
    nop
    nop                         /* stock all-zero Consumer Control release */

handled:
    movs    r1, #0              /* route to the stock unknown-command tail */

finish:
    mov     r0, r4
    cmp     r1, #0x3b
    bne     return_to_dispatch
    nop
    nop                         /* exact stock 0x3B handler */
    movs    r1, #0              /* stock compare chain reaches its tail */

return_to_dispatch:
    pop     {r4, pc}

    .balign 2
    .space 4, 0

.global rt12_hid_bridge_end
rt12_hid_bridge_end:
