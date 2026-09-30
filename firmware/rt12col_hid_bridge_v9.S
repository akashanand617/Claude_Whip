.syntax unified
.cpu cortex-m0plus
.thumb

/*
 * Offline RT12COL V9 candidate. The exact LIS2DW12/0x44 image retires both
 * selectors of the STK8321/0x23 initializer at 0xbf30. Its only direct call
 * into the adjacent STK helper at 0xbf14 is inside that retired initializer.
 *
 * A2 action 0..3: unchanged V8 mouse swipes.
 * A2 action 4..8: wheel up +5..+1; 9: no-op; 10..14: down -1..-5.
 * A2 action 0x20..0x29: Consumer bit 0..9.
 * A2 action (0x80 | USB keycode): keycode in the final ID4 array byte.
 * The V9 sender rejects every other post-subtraction value.
 *
 * Six NOP pairs are replaced by pinned Thumb BL instructions by the builder.
 */

.section .text.rt12_hid_wheel,"ax",%progbits
.global rt12_hid_wheel_begin
.thumb_func
rt12_hid_wheel_begin:
    push    {r4, lr}
    cmp     r0, #15
    bhs     wheel_done           /* Consumer/unknown: preserve r0 */
    movs    r3, #9
    subs    r3, r0               /* signed wheel delta: +5..-5 */
    beq     wheel_finished       /* action 9: no mouse report */
    movs    r0, #0
    mov     r1, r0
    mov     r2, r0
    nop
    nop                         /* stock mouse sender at 0x3d70 */
wheel_finished:
    movs    r0, #0x30            /* after bridge -0x20: invalid sender 0x10 */
wheel_done:
    pop     {r4, pc}
    .space 2, 0
.global rt12_hid_wheel_end
rt12_hid_wheel_end:

.section .text.rt12_hid_bridge_v9,"ax",%progbits
.global rt12_hid_bridge_v9_begin
.thumb_func
rt12_hid_bridge_v9_begin:
    push    {r4, lr}
    mov     r4, r0
    cmp     r1, #0xa2
    bne     finish
    ldrb    r0, [r4, #1]
    cmp     r0, #4
    blo     swipe
    nop
    nop                         /* wheel helper: 4..13 send; others no-op */

consumer:
    subs    r0, #0x20
    nop
    nop                         /* V9 hybrid press or no-op */
    nop
    nop                         /* V9 hybrid all-zero release */
    b       handled

swipe:
    movs    r2, #1
    cmp     r0, #2
    bhs     horizontal
    movs    r1, #1
    cmp     r0, #0
    bne     vertical_ready
    rsbs    r1, r1, #0
vertical_ready:
    movs    r0, #0
    b       run_swipe
horizontal:
    movs    r1, #0
    subs    r0, #2
    lsls    r0, r0, #1
    subs    r0, #1
run_swipe:
    nop
    nop                         /* stock swipe scheduler */

handled:
    movs    r1, #0
finish:
    mov     r0, r4
    cmp     r1, #0x3b
    bne     return_to_dispatch
    nop
    nop                         /* exact stock 3B handler */
    movs    r1, #0
return_to_dispatch:
    pop     {r4, pc}
    .balign 2
    .space 4, 0
.global rt12_hid_bridge_v9_end
rt12_hid_bridge_v9_end:
