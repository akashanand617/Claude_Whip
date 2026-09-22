import sys, struct, collections
import capstone
path = sys.argv[1]
data = open(path,'rb').read()
PAY = 0x450
code = data[PAY:]
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB); md.detail = True
# linear-sweep disassembly with resync, addresses = file offsets
insns = []
pos = PAY
while pos < len(data)-2:
    dec = list(md.disasm(data[pos:], pos))
    if not dec:
        pos += 2; continue
    insns.extend(dec); pos = dec[-1].address + dec[-1].size + 2
print("insns", len(insns))
# prologue offsets (push {..., lr})
prol = set()
for i in insns:
    if i.mnemonic == 'push' and 'lr' in i.op_str: prol.add(i.address)
# also bl targets
bl_t = collections.Counter()
for i in insns:
    if i.mnemonic == 'bl':
        t = int(i.op_str.lstrip('#'),0); bl_t[t]+=1
print("distinct bl targets", len(bl_t), "in-file", sum(1 for t in bl_t if PAY<=t<len(data)))
# literal pool pointers: ldr rX,[pc,#imm]
lits = []
for i in insns:
    if i.mnemonic == 'ldr' and '[pc' in i.op_str:
        base = (i.address + 4) & ~3
        imm = 0
        if '#' in i.op_str:
            imm = int(i.op_str.split('#')[1].rstrip(']'),0)
        a = base + imm
        if a+4 <= len(data):
            v = struct.unpack_from('<I', data, a)[0]; lits.append((i.address, v))
vals = [v for _,v in lits]
print("literals", len(vals))
# region histogram
def region(v):
    if v < 0x100000: return 'ROM(<0x100000)'
    if 0x200000 <= v < 0x300000: return 'RAM(0x2xxxxx)'
    if 0x800000 <= v < 0x900000: return 'FLASH(0x8xxxxx)'
    if 0x40000000 <= v < 0x50000000: return 'PERIPH(0x4xxxxxxx)'
    if 0xE0000000 <= v: return 'SCS'
    return 'other'
print(collections.Counter(region(v) for v in vals).most_common())
# test candidate load bases for the payload: for odd flash literals, fraction on a prologue
cands = [0x826400, 0x826000, 0x826450, 0x826664-0x264]
for B in cands:
    odd = [v for v in vals if 0x800000 <= v < 0x900000 and v & 1]
    hit = sum(1 for v in odd if ((v-1) - B + PAY) in prol)
    inr = sum(1 for v in odd if 0 <= (v-1)-B < len(code))
    print(f"base {B:#x}: odd flash literals {len(odd)}, in-range {inr}, on push-lr prologue {hit}")
# brute-force scan of base over a range for the best prologue hit rate
odd = [v for v in vals if 0x800000 <= v < 0x900000 and v & 1]
best = []
for B in range(0x800000, 0x880000, 2):
    hit = sum(1 for v in odd if ((v-1) - B + PAY) in prol)
    best.append((hit, B))
best.sort(reverse=True)
print("top bases by prologue hits:", [(h, hex(b)) for h,b in best[:6]])
