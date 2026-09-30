.syntax unified
.cpu cortex-m0plus
.thumb
/*
 * Exact-size replacement for stock Consumer press/release at 0x3e1e..0x3e6f.
 * r0=0..9 emits one of ten Consumer bits; r0=0x80..0xb2 (from the A2 bridge)
 * emits one 8-bit Keyboard Array code. r0=0xff at the release entry emits an
 * all-zero report. All other inputs return without sending. The three fixed
 * PC-relative loads target unchanged stock literals at 0x3e7c/74/78 when
 * this section is placed at exact file offset 0x3e1e. The BL placeholder at
 * file offset 0x3e68 is filled by the pinned Python builder.
 */
.section .text.rt12_hid_sender_v9,"ax",%progbits
.global rt12_hid_press_v9
.thumb_func
rt12_hid_press_v9:
    b setup
.global rt12_hid_release_v9
.thumb_func
rt12_hid_release_v9:
    movs r0, #255
setup:
    push {r1, r2, r3, lr}
    movs r2, #0
    str r2, [sp, #8]
    cmp r0, #255
    beq send
    cmp r0, #0xb2              /* reject non-A2/reserved upper actions */
    bhi done
    cmp r0, #128
    bhs keyboard
    cmp r0, #10
    bhs done
    movs r1, #1
    lsls r1, r0
    mov r2, sp
    strh r1, [r2, #8]
    b send
keyboard:
    adds r0, #0x20            /* bridge had subtracted 0x20 */
    lsls r0, r0, #25
    lsrs r0, r0, #25
    mov r2, sp
    strb r0, [r2, #10]
send:
    ldr r0, [pc, #44]            /* stock 0x3e7c: HID enabled */
    ldrb r0, [r0]
    cmp r0, #0
    beq done
    movs r0, #3
    str r0, [sp]
    movs r0, #1
    str r0, [sp, #4]
    ldr r0, [pc, #20]            /* stock 0x3e74: HID attribute */
    ldr r1, [pc, #24]            /* stock 0x3e78: HID connection */
    ldrb r0, [r0, #0x12]
    ldrb r1, [r1]
    add r3, sp, #8
    movs r2, #24
    nop
    nop
done:
    pop {r1, r2, r3, pc}
    .space 2, 0
.global rt12_hid_sender_v9_end
rt12_hid_sender_v9_end:
