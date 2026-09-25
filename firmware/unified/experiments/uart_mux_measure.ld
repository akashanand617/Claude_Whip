/* MEASUREMENT ONLY: unowned historical holes plus gross FEE7 spans.
 * This is not a stock edit, ownership proof, production placement or image. */
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
f0 (rx) : ORIGIN = 0x82db44, LENGTH = 0x2c
f1 (rx) : ORIGIN = 0x82db70, LENGTH = 0x12
f2 (rx) : ORIGIN = 0x82db82, LENGTH = 0x24
f3 (rx) : ORIGIN = 0x82dba6, LENGTH = 0xaa
f4 (rx) : ORIGIN = 0x82dc50, LENGTH = 0x6e
f5 (rx) : ORIGIN = 0x82dcbe, LENGTH = 0x50
f6 (rx) : ORIGIN = 0x82dd0e, LENGTH = 0x44
f7 (rx) : ORIGIN = 0x8442c0, LENGTH = 0xfc
f8 (rx) : ORIGIN = 0x8443bc, LENGTH = 0x0c
}
PHDRS {
p0 PT_LOAD FLAGS(5); p1 PT_LOAD FLAGS(5); p2 PT_LOAD FLAGS(5);
p3 PT_LOAD FLAGS(5); p4 PT_LOAD FLAGS(5); p5 PT_LOAD FLAGS(5);
p6 PT_LOAD FLAGS(5); p7 PT_LOAD FLAGS(5);
f0 PT_LOAD FLAGS(5); f1 PT_LOAD FLAGS(5); f2 PT_LOAD FLAGS(5);
f3 PT_LOAD FLAGS(5); f4 PT_LOAD FLAGS(5); f5 PT_LOAD FLAGS(5);
f6 PT_LOAD FLAGS(5); f7 PT_LOAD FLAGS(5); f8 PT_LOAD FLAGS(5);
app PT_LOAD FLAGS(5); unwind PT_LOAD FLAGS(4);
}
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

.fee7_helper : { *(.text.wt_start) } >f0 :f0
ASSERT(SIZEOF(.fee7_helper) == 42, "FEE7 helper trial changed")
.fee7_indicate : { *(.text.wim_init) } >f1 :f1
ASSERT(SIZEOF(.fee7_indicate) == 14, "FEE7 indicate trial changed")
.fee7_confirm : { *(.text.action_matches) } >f2 :f2
ASSERT(SIZEOF(.fee7_confirm) == 36, "FEE7 confirm trial changed")
.fee7_read : { *(.text.wim_post) *(.text.wr_init) } >f3 :f3
ASSERT(SIZEOF(.fee7_read) == 160, "FEE7 read trial changed")
.fee7_write : { *stock_uart_mux.o(.text) *(.text.wt_stop) } >f4 :f4
ASSERT(SIZEOF(.fee7_write) == 110, "FEE7 write trial changed")
.fee7_cccd : { *(.text.wop_retire) } >f5 :f5
ASSERT(SIZEOF(.fee7_cccd) == 76, "FEE7 CCCD trial changed")
.fee7_add : { *(.text.enter) } >f6 :f6
ASSERT(SIZEOF(.fee7_add) == 60, "FEE7 add trial changed")
.fee7_database : { *(.text.wop_read) *(.text.wim_retire) } >f7 :f7
ASSERT(SIZEOF(.fee7_database) == 252, "FEE7 database trial changed")
.fee7_callbacks : { *(.text.wt_init) } >f8 :f8
ASSERT(SIZEOF(.fee7_callbacks) == 10, "FEE7 callback trial changed")

.text : { *(.text*) *(.rodata*) } >app :app
.ARM.exidx : { *(.ARM.exidx*) } >app :unwind
.data : { *(.data*) } >app :app
.bss (NOLOAD) : { *(.bss*) *(COMMON) } >app :app
/DISCARD/ : { *(.comment) *(.note*) }
}
ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "no static RAM approved")
