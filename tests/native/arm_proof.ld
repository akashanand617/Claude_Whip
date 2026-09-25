/* EMULATOR ONLY. These addresses intentionally are NOT the RT02CR layout.
 * Never use this ELF as input to an OTA packer or patch it into stock.
 */
ENTRY(wr_init)
MEMORY {
    proof_code (rx) : ORIGIN = 0x01000000, LENGTH = 64K
}
SECTIONS {
    .text : { *(.text*) *(.rodata*) } > proof_code
    .ARM.exidx : { *(.ARM.exidx*) } > proof_code
    .data : { *(.data*) } > proof_code
    .bss (NOLOAD) : { *(.bss*) *(COMMON) } > proof_code
    /DISCARD/ : { *(.comment) *(.note*) }
}
ASSERT(SIZEOF(.data) == 0, "unexpected global writable data")
ASSERT(SIZEOF(.bss) == 0, "unexpected global BSS")
