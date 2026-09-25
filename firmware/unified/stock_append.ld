/* Real RT02CR STOCK append-address link, not a complete firmware image.
 * Preserve every byte of the stock image, including its last 200-byte overlay.
 * These configured bounds do not qualify chip/erase/recovery or RAM ownership.
 * No new writable static allocation is permitted by this link.
 */
ENTRY(wd_init)
MEMORY {
    append (rx) : ORIGIN = 0x847ad0, LENGTH = 0x2530
}
SECTIONS {
    .text : { *(.text*) *(.rodata*) } > append
    .ARM.exidx : { *(.ARM.exidx*) } > append
    .data : { *(.data*) } > append
    .bss (NOLOAD) : { *(.bss*) *(COMMON) } > append
    /DISCARD/ : { *(.comment) *(.note*) }
}
ASSERT(SIZEOF(.data) == 0, "no initialized static RAM allocation approved")
ASSERT(SIZEOF(.bss) == 0, "no static BSS allocation approved")
ASSERT(ADDR(.text) == 0x847ad0, "must preserve all stock bytes")
/* LLD 20.1.2 evaluates ASSERT before compacting ARM unwind entries. Its final
 * MEMORY-region check enforces the same 0x84a000 end after layout converges.
 * Do not enlarge this region or discard unwind data to make a link succeed.
 * A successful link also requires fwstock_link.inspect_elf's independent
 * final section/segment extent and exact-mapping checks before any report.
 */
