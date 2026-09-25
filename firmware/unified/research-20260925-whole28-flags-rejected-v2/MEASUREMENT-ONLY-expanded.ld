/* UNOWNED CONDITIONAL HOLES; NO ENTRY RETIREMENT; NEVER INSTALL. */
ENTRY(wd_init)
MEMORY {
app (rx) : ORIGIN = 0x847ad0, LENGTH = 0x5000
h0 (rx) : ORIGIN = 0x827e00, LENGTH = 0xf0
h1 (rx) : ORIGIN = 0x827f20, LENGTH = 0x194
h2 (rx) : ORIGIN = 0x8280b8, LENGTH = 0x240
h3 (rx) : ORIGIN = 0x829a78, LENGTH = 0x50
h4 (rx) : ORIGIN = 0x829ad0, LENGTH = 0x30
h5 (rx) : ORIGIN = 0x829b30, LENGTH = 0x98
h6 (rx) : ORIGIN = 0x829bcc, LENGTH = 0x80
h7 (rx) : ORIGIN = 0x82aab8, LENGTH = 0x12c
h8 (rx) : ORIGIN = 0x82abec, LENGTH = 0x80
}
PHDRS {
p0 PT_LOAD FLAGS(5);
p1 PT_LOAD FLAGS(5);
p2 PT_LOAD FLAGS(5);
p3 PT_LOAD FLAGS(5);
p4 PT_LOAD FLAGS(5);
p5 PT_LOAD FLAGS(5);
p6 PT_LOAD FLAGS(5);
p7 PT_LOAD FLAGS(5);
p8 PT_LOAD FLAGS(5);
app PT_LOAD FLAGS(5); unwind PT_LOAD FLAGS(4); }
SECTIONS {
.trial_stock_health_commit : { *stock_health_commit.o(.text) } >h0 :p0
ASSERT(SIZEOF(.trial_stock_health_commit) == 196, "whole text changed")
.trial_stock_timer_fence : { *stock_timer_fence.o(.text) } >h1 :p1
ASSERT(SIZEOF(.trial_stock_timer_fence) == 390, "whole text changed")
.trial_mode_controller : { *mode_controller.o(.text) } >h2 :p2
ASSERT(SIZEOF(.trial_mode_controller) == 544, "whole text changed")
.trial_stock_result_commit : { *stock_result_commit.o(.text) } >h3 :p3
ASSERT(SIZEOF(.trial_stock_result_commit) == 80, "whole text changed")
.trial_stock_schedule_settings : { *stock_schedule_settings.o(.text) } >h4 :p4
ASSERT(SIZEOF(.trial_stock_schedule_settings) == 48, "whole text changed")
.trial_compiler_runtime : { *compiler_runtime.o(.text) } >h5 :p5
ASSERT(SIZEOF(.trial_compiler_runtime) == 152, "whole text changed")
.trial_stock_binding : { *stock_binding.o(.text) } >h6 :p6
ASSERT(SIZEOF(.trial_stock_binding) == 128, "whole text changed")
.trial_stock_health_timers : { *stock_health_timers.o(.text) } >h7 :p7
ASSERT(SIZEOF(.trial_stock_health_timers) == 292, "whole text changed")
.trial_stock_legacy_gate : { *stock_legacy_gate.o(.text) } >h8 :p8
ASSERT(SIZEOF(.trial_stock_legacy_gate) == 64, "whole text changed")
.text : { *(.text*) *(.rodata*) } >app :app
.ARM.exidx : { *(.ARM.exidx*) } >app :unwind
.data : { *(.data*) } >app :app
.bss (NOLOAD) : { *(.bss*) *(COMMON) } >app :app
/DISCARD/ : { *(.comment) *(.note*) }
}
ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "no static RAM approved")