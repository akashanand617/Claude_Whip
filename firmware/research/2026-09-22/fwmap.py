#!/usr/bin/env python
"""
Annotated function map of the RT02CR application image (Realtek RTL8762E, Cortex-M0+).

    python fwmap.py build [image]          -> writes <scratch>/fw/listing.txt, functions.json
    python fwmap.py func 0xFILEOFF          -> annotated disassembly of the function containing that file offset
    python fwmap.py xref 0xFILEOFF          -> callers (bl) and literal-pointer references to that file offset
    python fwmap.py grep REGEX              -> grep the annotated listing (prints matching lines with function names)
    python fwmap.py calls NAME_OR_ADDR      -> every call site of a ROM symbol (e.g. os_timer_create) with the function it sits in
    python fwmap.py str                     -> strings and the functions that reference them

Addresses: FILE offsets everywhere (what xxd/patching use). abs = file - 0x450 + 0x826400.
"""
from __future__ import annotations
import json, re, struct, sys, os, collections
import capstone
from pathlib import Path

SCR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCR, 'fw')
DEFAULT_IMAGE = str(Path(__file__).resolve().parents[2] / 'rt02cr-25hz.bin')
PAY, BASE = 0x450, 0x826400
RAM_LO, RAM_HI = 0x200000, 0x220000

PERIPH = [
    (0x40000000, 0x100, 'SYSTEM_REG'), (0x40000100, 0x80, 'RTC'), (0x40000180, 0x10, 'LPC'), (0x40000190, 0x70, 'AON_WDG'),
    (0x40000200, 0x80, 'SYSBLKCTRL'), (0x40000280, 0xe0, 'PINMUX'), (0x40000360, 0x8, 'PWM2/CLKSRC2'),
    (0x40001000, 0x100, 'GPIO'), (0x40002000, 0x14, 'TIM0'), (0x40002014, 0x14, 'TIM1'), (0x40002028, 0x14, 'TIM2'),
    (0x4000203C, 0x14, 'TIM3'), (0x40002050, 0x14, 'TIM4'), (0x40002064, 0x14, 'TIM5'), (0x40002078, 0x14, 'TIM6'),
    (0x4000208C, 0x30, 'TIM7'), (0x400020B0, 0x50, 'TIM_LOADCNT2'), (0x40004000, 0x1000, 'QDEC'), (0x40005000, 0x1000, 'KEYSCAN'),
    (0x40006000, 0x1000, 'WDG/VENDOR'), (0x40007000, 0x1000, 'CACHE'), (0x40008000, 0x1000, 'ENHTIM'), (0x40009000, 0x1000, 'CAPTOUCH'),
    (0x40010000, 0x1000, 'ADC'), (0x40011000, 0x1000, 'UART1'), (0x40012000, 0x1000, 'UART0'), (0x40013000, 0x400, 'SPI0'),
    (0x40013400, 0x400, 'SPI1'), (0x40014000, 0x1000, 'HW_AES'), (0x40015000, 0x400, 'I2C0'), (0x40015400, 0x400, 'I2C1'),
    (0x40016000, 0x1000, 'IR'), (0x40020000, 0x1000, 'I2S0'), (0x40027000, 0x1000, 'GDMA'), (0x40080000, 0x1000, 'SPIC0'),
    (0x40050000, 0x8000, 'BT_BB'), (0x40058000, 0x8000, 'BT_VENDOR'), (0xE000E000, 0x1000, 'SCS/NVIC'),
]
I2C_REGS = {0x00: 'IC_CON', 0x04: 'IC_TAR', 0x08: 'IC_SAR', 0x10: 'IC_DATA_CMD', 0x14: 'SS_HCNT', 0x18: 'SS_LCNT',
            0x1c: 'FS_HCNT', 0x20: 'FS_LCNT', 0x2c: 'INTR_STAT', 0x30: 'INTR_MASK', 0x34: 'RAW_INTR', 0x38: 'RX_TL',
            0x3c: 'TX_TL', 0x40: 'CLR_INTR', 0x54: 'CLR_TX_ABRT', 0x6c: 'IC_ENABLE', 0x70: 'IC_STATUS', 0x74: 'TXFLR',
            0x78: 'RXFLR', 0x7c: 'SDA_HOLD', 0x80: 'TX_ABRT_SRC', 0x9c: 'ENABLE_STATUS'}
GPIO_REGS = {0x00: 'DATAOUT', 0x04: 'DATADIR', 0x08: 'DATASRC', 0x30: 'INTEN', 0x34: 'INTMASK', 0x38: 'INTTYPE',
             0x3c: 'INTPOL', 0x40: 'INTSTATUS', 0x44: 'RAWINT', 0x48: 'DEBOUNCE', 0x4c: 'INTCLR', 0x50: 'DATAIN'}


def periph_name(v):
    for base, size, name in PERIPH:
        if base <= v < base + size:
            off = v - base
            extra = ''
            if name.startswith('I2C') and off in I2C_REGS: extra = '.' + I2C_REGS[off]
            if name == 'GPIO' and off in GPIO_REGS: extra = '.' + GPIO_REGS[off]
            return f'{name}{extra}' + (f'+{off:#x}' if off and not extra else '')
    return None


def load_syms():
    syms = {}
    p = os.path.join(SCR, 'rom_symbol_gcc.axf')
    if os.path.exists(p):
        for line in open(p, errors='replace'):
            m = re.match(r'\s*(\w+)\s*=\s*(0x[0-9a-fA-F]+)', line)
            if m: syms[int(m.group(2), 16)] = m.group(1)
    return syms


def f2a(f): return f - PAY + BASE
def a2f(a): return a - BASE + PAY
def in_app(a, n): return BASE <= a < BASE + n - PAY


class Image:
    def __init__(self, path=DEFAULT_IMAGE):
        self.path = path
        self.data = open(path, 'rb').read()
        self.syms = load_syms()
        self.md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        self.disasm_all()
        self.map_functions()

    def disasm_all(self):
        d, md = self.data, self.md
        insns = []
        pos = PAY
        while pos < len(d) - 2:
            dec = list(md.disasm(d[pos:], pos))
            if not dec:
                pos += 2; continue
            insns.extend(dec); pos = dec[-1].address + dec[-1].size + 2
        self.insns = insns
        self.by_addr = {i.address: i for i in insns}
        # literal loads
        self.lits = {}   # insn addr -> (pool addr, value)
        for i in insns:
            if i.mnemonic == 'ldr' and '[pc' in i.op_str:
                base = (i.address + 4) & ~3
                imm = int(i.op_str.split('#')[1].rstrip(']'), 0) if '#' in i.op_str else 0
                a = base + imm
                if a + 4 <= len(d):
                    self.lits[i.address] = (a, struct.unpack_from('<I', d, a)[0])
        self.pool_addrs = set(a for a, _ in self.lits.values())
        # bl targets (file space)
        self.bl = {}
        for i in insns:
            if i.mnemonic == 'bl':
                t = int(i.op_str.lstrip('#'), 0)
                self.bl[i.address] = t

    def map_functions(self):
        n = len(self.data)
        starts = set()
        for t in self.bl.values():
            if PAY <= t < n: starts.add(t)
        for _, (_, v) in self.lits.items():
            if in_app(v, n) and v & 1: starts.add(a2f(v - 1))
        for i in self.insns:
            if i.mnemonic == 'push' and 'lr' in i.op_str: starts.add(i.address)
        starts.add(PAY)
        self.starts = sorted(s for s in starts if PAY <= s < n)
        self.funcs = {}
        for k, s in enumerate(self.starts):
            e = self.starts[k + 1] if k + 1 < len(self.starts) else n
            self.funcs[s] = e
        # callers / refs
        self.callers = collections.defaultdict(list)
        for at, t in self.bl.items():
            self.callers[t].append(at)
        self.ptr_refs = collections.defaultdict(list)  # file offset -> [insn addr]
        for at, (_, v) in self.lits.items():
            if in_app(v, n):
                self.ptr_refs[a2f(v & ~1) if v & 1 else a2f(v)].append(at)
        self.strings = self.find_strings()

    def find_strings(self):
        d = self.data; out = {}
        i = PAY
        while i < len(d):
            if 0x20 <= d[i] < 0x7f:
                j = i
                while j < len(d) and 0x20 <= d[j] < 0x7f: j += 1
                if j - i >= 4 and j < len(d) and d[j] == 0:
                    out[i] = d[i:j].decode('ascii')
                i = j + 1
            else:
                i += 1
        return out

    def func_of(self, off):
        import bisect
        k = bisect.bisect_right(self.starts, off) - 1
        return self.starts[max(k, 0)]

    def name(self, off):
        return f'sub_{off:05x}'

    def annotate(self, i):
        n = len(self.data)
        notes = []
        if i.mnemonic == 'bl':
            t = self.bl[i.address]
            ta = (f2a(t)) & 0xffffffff
            if PAY <= t < n:
                notes.append(f'-> {self.name(t)}')
            elif ta < 0x100000:
                notes.append(f'-> ROM {self.syms.get(ta | 1, f"rom_{ta:05x}")}')
            else:
                notes.append(f'-> ?? abs {ta:#x}')
        if i.address in self.lits:
            a, v = self.lits[i.address]
            tag = f'={v:#x}'
            if in_app(v, n):
                f = a2f(v & ~1)
                if v & 1 and f in self.funcs: tag += f' &{self.name(f)}'
                elif f in self.strings: tag += f' "{self.strings[f]}"'
                else:
                    ff = a2f(v)
                    tag += f' app@file {ff:#x}' + (f' "{self.strings[ff]}"' if ff in self.strings else '')
            elif v < 0x100000:
                if (v | 1) in self.syms: tag += f' ROM {self.syms[v | 1]}'
            elif RAM_LO <= v < RAM_HI:
                tag += ' RAM'
            else:
                p = periph_name(v)
                if p: tag += f' {p}'
            notes.append(tag)
        return '  ; ' + ' '.join(notes) if notes else ''

    def func_text(self, start):
        end = self.funcs[start]
        lines = []
        callers = self.callers.get(start, [])
        refs = self.ptr_refs.get(start, [])
        hdr = f'; ===== {self.name(start)}  file {start:#x}  abs {f2a(start):#x}  size {end - start}'
        hdr += f'  callers[{len(callers)}]: ' + ' '.join(self.name(self.func_of(c)) for c in sorted(set(callers))[:12])
        if refs: hdr += f'  ptr-refs[{len(refs)}]: ' + ' '.join(self.name(self.func_of(r)) for r in sorted(set(refs))[:8])
        lines.append(hdr)
        a = start
        while a < end:
            if a in self.pool_addrs:
                v = struct.unpack_from('<I', self.data, a)[0]
                lines.append(f'{a:06x}  {v:08x}          .word {v:#x}')
                a += 4; continue
            i = self.by_addr.get(a)
            if i is None:
                lines.append(f'{a:06x}  {self.data[a:a+2].hex()}              .hword')
                a += 2; continue
            lines.append(f'{a:06x}  {i.bytes.hex():<10}  {i.mnemonic:<7} {i.op_str}{self.annotate(i)}')
            a += i.size
        return '\n'.join(lines)

    def build(self):
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, 'listing.txt'), 'w') as f:
            for s in self.starts:
                f.write(self.func_text(s) + '\n\n')
        fj = {}
        for s in self.starts:
            e = self.funcs[s]
            calls = sorted(set(self.name(t) if PAY <= t < len(self.data) else self.syms.get((f2a(t) & 0xffffffff) | 1, f'rom_{(f2a(t)&0xffffffff):05x}')
                               for at, t in self.bl.items() if s <= at < e))
            fj[self.name(s)] = {'file': s, 'abs': f2a(s), 'size': e - s,
                               'callers': sorted(set(self.name(self.func_of(c)) for c in self.callers.get(s, []))),
                               'calls': calls}
        json.dump(fj, open(os.path.join(OUT, 'functions.json'), 'w'), indent=0)
        print(f'functions {len(self.starts)}, insns {len(self.insns)}, strings {len(self.strings)} -> {OUT}')


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    img = Image(sys.argv[2] if cmd == 'build' and len(sys.argv) > 2 else DEFAULT_IMAGE)
    if cmd == 'build':
        img.build()
    elif cmd == 'func':
        for a in sys.argv[2:]:
            print(img.func_text(img.func_of(int(a, 0)))); print()
    elif cmd == 'xref':
        off = int(sys.argv[2], 0)
        f = img.func_of(off)
        print(f'{img.name(f)} (file {f:#x}) containing {off:#x}')
        for c in sorted(set(img.callers.get(f, []))): print(f'  bl from {c:#x} in {img.name(img.func_of(c))}')
        for r in sorted(set(img.ptr_refs.get(f, []))): print(f'  ptr from {r:#x} in {img.name(img.func_of(r))}')
        for r in sorted(set(img.ptr_refs.get(off, []))):
            if off != f: print(f'  data ptr to {off:#x} from {r:#x} in {img.name(img.func_of(r))}')
    elif cmd == 'grep':
        rx = re.compile(sys.argv[2])
        cur = None
        for line in open(os.path.join(OUT, 'listing.txt')):
            if line.startswith('; ====='): cur = line.split()[2]
            elif rx.search(line): print(f'{cur:<10} {line.rstrip()}')
    elif cmd == 'calls':
        key = sys.argv[2]
        want = None
        for a, nm in img.syms.items():
            if nm == key: want = a & ~1
        if want is None: want = int(key, 0)
        for at, t in sorted(img.bl.items()):
            ta = f2a(t) & 0xffffffff
            if (ta if ta < 0x100000 else t) == want or t == want:
                print(f'  {at:#x} in {img.name(img.func_of(at))}')
    elif cmd == 'str':
        for off, s in sorted(img.strings.items()):
            refs = sorted(set(img.name(img.func_of(r)) for r in img.ptr_refs.get(off, [])))
            if refs or re.search(r'[a-z]{3}', s): print(f'{off:#07x} {s!r:<50} {" ".join(refs)}')
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
