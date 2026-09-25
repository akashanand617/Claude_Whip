.syntax unified
.cpu cortex-m0plus
.thumb

/* OFF-RING conditional-optics experiment for the exact 25 Hz image.
 * These helpers are linked over the unregistered FEE7 attribute database.
 * They preserve stock Health unless the existing raw-mode byte equals four.
 */

.equ RAW_MODE,             0x209cac
.equ LINK_STATE,           0x209e09
.equ SENSOR_SETUP,         0x829c59
.equ SENSOR_ENABLE_NEXT,   0x835645
.equ CHIP_WRITE,           0x834c93
.equ DISCONNECT_ORIGINAL,  0x82cff3
.equ TIMER_STOP_DELETE,    0x829ce9

.section .text.sensor_enable_gate,"ax",%progbits
.global sensor_enable_gate
.type sensor_enable_gate,%function
.thumb_func
sensor_enable_gate:
    ldr     r1, =RAW_MODE
    ldrb    r1, [r1]
    cmp     r1, #4
    beq     1f
    /* The entry hook supplied the original caller LR in r3. Recreate the
     * overwritten prologue and call at file 0xf68c..0xf693. */
    mov     lr, r3
    push    {r3-r7, lr}
    mov     r4, r0
    ldr     r3, =SENSOR_SETUP
    blx     r3
    ldr     r3, =SENSOR_ENABLE_NEXT
    bx      r3
1:  bx      r3
.size sensor_enable_gate, .-sensor_enable_gate

.section .text.idle_guard,"ax",%progbits
.global idle_guard
.type idle_guard,%function
.thumb_func
idle_guard:
    ldr     r0, =RAW_MODE
    ldrb    r0, [r0]
    cmp     r0, #4
    bne     1f
    ldr     r0, =LINK_STATE
    ldrb    r0, [r0]
    cmp     r0, #2
    bne     1f
    movs    r0, #0
    bx      lr
1:  ldrb    r0, [r4, #6]
    cmp     r0, #0
    bx      lr
.size idle_guard, .-idle_guard

.section .text.chip_control,"ax",%progbits
.global chip_control
.type chip_control,%function
.thumb_func
chip_control:
    mov     lr, r3
    push    {r3, lr}
    movs    r1, #0
    mov     r2, sp
    strb    r1, [r2]
    cmp     r0, #0
    beq     1f
    cmp     r0, #1
    beq     2f
    cmp     r0, #2
    beq     4f
    movs    r0, #1
    pop     {r3, pc}
1:  strb    r1, [r2]
    b       5f
2:  ldr     r3, =RAW_MODE
    ldrb    r3, [r3]
    cmp     r3, #4
    bne     3f
    movs    r0, #0
    b       5f
3:  movs    r0, #0x5a
    b       5f
4:  movs    r0, #0xa5
5:  strb    r0, [r2]
    movs    r2, #1
    mov     r1, sp
    movs    r0, #0x7b
    ldr     r3, =CHIP_WRITE
    blx     r3
    pop     {r3, pc}
.size chip_control, .-chip_control

.section .text.disconnect_cleanup,"ax",%progbits
.global disconnect_cleanup
.type disconnect_cleanup,%function
.thumb_func
disconnect_cleanup:
    push    {r4, lr}
    ldr     r3, =DISCONNECT_ORIGINAL
    blx     r3
    ldr     r4, =RAW_MODE
    ldrb    r0, [r4]
    cmp     r0, #4
    bne     1f
    movs    r0, #0
    strb    r0, [r4]
    mov     r0, r4
    adds    r0, #0x10
    ldr     r3, =TIMER_STOP_DELETE
    blx     r3
1:  pop     {r4, pc}
.size disconnect_cleanup, .-disconnect_cleanup
