#!/bin/bash
# Offline measurement only. Usage: reproduce.sh /path/to/zig-0.15.2
# Links the PINNED checkpoint stock-address objects (not live sources, which
# keep changing) plus a fresh unified_state.o, under both linker variants.
# Writes nothing in-tree. The state object is compiled against CURRENT headers;
# the script refuses if the struct layout has drifted from the recorded 0x48c.
set -euo pipefail
ZIG=${1:?zig path}; HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../../../.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export ZIG_GLOBAL_CACHE_DIR=$T/zc ZIG_LOCAL_CACHE_DIR=$T/zl
FLAGS=(--target=armv6m-none-eabi -mcpu=cortex-m0plus -mthumb -ffreestanding -fno-builtin -Oz -std=c11
       -Wall -Wextra -Werror -fstack-usage -I "$ROOT/firmware/unified")
CKPT=$ROOT/firmware/unified/build-20260924-layout-candidates-v1/stock-address
OBJS=()
for s in mode_controller sample_tap runtime health_adapter fresh_source adapter stock_binding wire dispatch \
         stock_transport stock_timer_fence stock_health_timers stock_schedule_settings stock_result_commit \
         stock_optical_work stock_optical_io compiler_runtime; do OBJS+=("$CKPT/$s.o"); done
clang "${FLAGS[@]}" -c "$HERE/unified_state.c" -o "$T/unified_state.o"
link() { "$ZIG" cc -target thumb-freestanding-eabi -mcpu=cortex_m0plus -nostdlib -Wl,-T,"$1" -Wl,-e,wd_init \
         -Wl,--build-id=none -Wl,--no-undefined -Wl,-z,max-page-size=4 -o "$2" "${OBJS[@]}" "$T/unified_state.o"; }
if link "$HERE/strict_assert.ld" "$T/strict.elf" 2>"$T/strict.err"; then echo "strict: linked"
else echo "strict: REFUSED ($(head -1 "$T/strict.err"))"; fi
link "$HERE/region_only.ld" "$T/region.elf"
llvm-objdump -h "$T/region.elf" | grep -E "text|exidx|unified_state"
llvm-objdump -h "$T/region.elf" | grep -q "unified_state  0000048c 0020e738" || { echo "layout drifted"; exit 1; }
llvm-objdump -p "$T/region.elf" | grep -A1 "vaddr 0x0020e738"
