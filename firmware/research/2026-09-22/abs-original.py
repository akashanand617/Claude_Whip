import re, struct, collections, sys, capstone
S='/private/tmp/claude-501/-Users-akashanand-Claude-Whip/fce5503d-9fbc-4aa8-93c0-bd04600def2d/scratchpad'
syms={}
for line in open(S+'/rom_symbol_gcc.axf', errors='replace'):
    m=re.match(r'\s*(\w+)\s*=\s*(0x[0-9a-fA-F]+)',line)
    if m: syms[int(m.group(2),16)]=m.group(1)
data=open(sys.argv[1] if len(sys.argv)>1 else 'firmware/rt02cr-25hz.bin','rb').read()
PAY=0x450; BASE=0x826400
def f2a(f): return f-PAY+BASE
def a2f(a): return a-BASE+PAY
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB)
insns=[]; pos=PAY
while pos<len(data)-2:
    dec=list(md.disasm(data[pos:],pos))
    if not dec: pos+=2; continue
    insns.extend(dec); pos=dec[-1].address+dec[-1].size+2
prol=set(i.address for i in insns if i.mnemonic=='push' and 'lr' in i.op_str)
# BL targets in absolute space
bl=collections.Counter()
for i in insns:
    if i.mnemonic=='bl':
        t=int(i.op_str.lstrip('#'),0)  # file-offset space (may wrap)
        t=(t-PAY+BASE)&0xffffffff
        bl[t]+=1
def region(v):
    if v<0x100000: return 'ROM'
    if 0x200000<=v<0x220000: return 'RAM'
    if 0x800000<=v<BASE: return 'FLASH_BELOW_APP'
    if BASE<=v<BASE+len(data)-PAY: return 'APP'
    if 0x40000000<=v<0x50000000: return 'PERIPH'
    return 'other'
print('BL target regions:', collections.Counter(region(t) for t in bl).most_common())
rom=[(t,c) for t,c in bl.items() if region(t)=='ROM']
named=[(t,c) for t,c in rom if t in syms]
print(f'ROM BL targets {len(rom)} distinct, named {len(named)}')
for t,c in sorted(rom, key=lambda x:-x[1]):
    print(f'  {t:#08x} x{c:<4} {syms.get(t,"?")}')
below=[(t,c) for t,c in bl.items() if region(t)=='FLASH_BELOW_APP']
print(f'\nBL into flash below app (upperstack/patch): {len(below)} distinct')
for t,c in sorted(below, key=lambda x:-x[1])[:40]: print(f'  {t:#08x} x{c}')
oth=[(t,c) for t,c in bl.items() if region(t) in ('other','RAM','PERIPH')]
print('\nother BL targets:', [(hex(t),c) for t,c in sorted(oth,key=lambda x:-x[1])[:20]])
# literal pools
lits=[]
for i in insns:
    if i.mnemonic=='ldr' and '[pc' in i.op_str:
        base=(i.address+4)&~3; imm=int(i.op_str.split('#')[1].rstrip(']'),0) if '#' in i.op_str else 0
        a=base+imm
        if a+4<=len(data): lits.append((i.address, struct.unpack_from('<I',data,a)[0]))
ramodd=[v for _,v in lits if 0x200000<=v<0x220000 and v&1]
print('\nodd RAM literals', len(ramodd))
best=[]
for D in range(0x200000-0x20000, 0x220000, 2):
    hit=sum(1 for v in ramodd if ((v-1)-D+0) in prol)  # D maps file offset 0 -> RAM addr D
    if hit: best.append((hit,D))
best.sort(reverse=True); print('RAM code mapping candidates (file0->ram):', [(h,hex(d)) for h,d in best[:8]])
# peripheral literal users
per=collections.defaultdict(set)
for at,v in lits:
    if 0x40000000<=v<0x50000000: per[v&0xfffff000 if v>=0x40010000 else v&0xffffff00].add(at)
print('\nperipheral bases referenced (masked):')
for b,ats in sorted(per.items()): print(f'  {b:#010x} x{len(ats)}  first sites {[hex(a) for a in sorted(ats)[:6]]}')
