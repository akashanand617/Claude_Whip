ENTRY(sensor_enable_gate)
SECTIONS
{
  . = 0x8450d8;
  .text :
  {
    *(.text.sensor_enable_gate)
    *(.text.idle_guard)
    *(.text.chip_control)
    *(.text.disconnect_cleanup)
  }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
