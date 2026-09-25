/* RESEARCH DERIVATIVE of firmware/unified/stock_append.ld, NOT a builder input.
 * Adds one NOLOAD state section at the UNAPPROVED candidate 0x20e738..0x20ec00.
 */
/* Real RT02CR STOCK append-address link, not a complete firmware image.
 * Preserve every byte of the stock image, including its last 200-byte overlay.
 * These configured bounds do not qualify chip/erase/recovery or RAM ownership.
 * No new writable static allocation is permitted by this link.
 */
ENTRY(wd_init)
MEMORY {
    unified_ram (rw) : ORIGIN = 0x20e738, LENGTH = 0x4c8
    append (rx) : ORIGIN = 0x847ad0, LENGTH = 0x2530
}
SECTIONS {
    .text : { *(.text*) *(.rodata*) } > append
    .ARM.exidx : { *(.ARM.exidx*) } > append
    .unified_state 0x20e738 (NOLOAD) : { KEEP(*(.bss.unified_state)) } > unified_ram
    .data : { *(.data*) } > append
    .bss (NOLOAD) : { *(.bss*) *(COMMON) } > append
    /DISCARD/ : { *(.comment) *(.note*) }
}
ASSERT(SIZEOF(.data) == 0, "no initialized static RAM allocation approved")
ASSERT(SIZEOF(.bss) == 0, "no static BSS allocation approved")
ASSERT(ADDR(.text) == 0x847ad0, "must preserve all stock bytes")
ASSERT(ADDR(.ARM.exidx) + SIZEOF(.ARM.exidx) <= 0x84a000, "configured APP bound exceeded")
ASSERT(ADDR(.unified_state) == 0x20e738, "state must start at the candidate region")
ASSERT(ADDR(.unified_state) + SIZEOF(.unified_state) <= 0x20ec00, "state exceeds app RAM reservation")
