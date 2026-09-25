"""Fixed-stock FEE7 reference survey; never patches, links or touches hardware."""
from pathlib import Path
import hashlib
import json
import struct
import sys
import capstone
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC

ROOT = Path('/Users/akashanand/Claude_Whip')
OUT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from whip.fwindicator import branch_candidate
from whip.fwram import EXEC_REGIONS

sha = lambda b: hashlib.sha256(b).hexdigest()
names = ['firmware/rt02cr-stock-3.12.02.bin', 'whip/fwindicator.py', 'whip/fwram.py']
inputs = {n: sha((ROOT/n).read_bytes()) for n in names}
raw = (ROOT/names[0]).read_bytes()
assert inputs[names[0]] == 'b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0'
BIAS = 0x825fb0
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_MCLASS)
md.detail = True
branches, literals, halfwords = [], [], 0

def file_of(address):
    return next((address-b for lo,hi,b in EXEC_REGIONS if lo+b <= address < hi+b), None)

for lo, hi, bias in EXEC_REGIONS:
    for off in range(lo, hi-1, 2):
        halfwords += 1
        branch = branch_candidate(raw, off, off+bias)
        if branch and (branch[0] != 'bl' or off+4 <= hi):
            branches.append({'site': off, 'kind': branch[0], 'target': branch[1],
                             'target_file': file_of(branch[1])})
        word = struct.unpack_from('<H',raw,off)[0]
        if word & 0xf800 in (0x4800, 0xa000):
            address = ((off+bias+4)&~3) + 4*(word&0xff)
            source = file_of(address)
            if source is not None and source+4 <= len(raw):
                literals.append({'site': off, 'kind': 'ldr' if word&0xf800==0x4800 else 'adr',
                    'literal_file': source, 'address': address,
                    'value': struct.unpack_from('<I',raw,source)[0]})
pointers = [(off,struct.unpack_from('<I',raw,off)[0]) for off in range(len(raw)-3)]

def disassemble(lo, hi):
    bias = next(b for a,z,b in EXEC_REGIONS if a<=lo<hi<=z)
    instructions = list(md.disasm(raw[lo:hi],lo+bias))
    assert sum(i.size for i in instructions)==hi-lo,(hex(lo),hex(hi))
    result=[]
    for i in instructions:
        row={'site':i.address-bias,'bytes':i.bytes.hex(),'mnemonic':i.mnemonic,'operands':i.op_str}
        for o in i.operands:
            if o.type==ARM_OP_MEM and o.mem.base==ARM_REG_PC:
                target=((i.address+4)&~3)+o.mem.disp
                off=file_of(target)
                row['pc_literal_file']=off
                row['pc_literal_value']=None if off is None else struct.unpack_from('<I',raw,off)[0]
        result.append(row)
    return result

specs=[('fee7_set_parameter',0x7b94,0x7bc0),('fee7_send_indication',0x7bc0,0x7bd2),
       ('fee7_read_confirmation',0x7bd2,0x7bf6),('fee7_read',0x7bf6,0x7ca0),
       ('fee7_write',0x7ca0,0x7d0e),('fee7_cccd',0x7d0e,0x7d5e),
       ('fee7_add',0x7d5e,0x7da2)]
spans=[]
for name,lo,hi in specs:
    instructions=disassemble(lo,hi)
    spans.append({'name':name,'lo':lo,'hi':hi,'bytes':hi-lo,'sha256':sha(raw[lo:hi]),
        'incoming_branch_candidates':[x for x in branches if x['target_file'] is not None and lo<=x['target_file']<hi and not lo<=x['site']<hi],
        'stored_pointer_candidates':[{'site':s,'value':v} for s,v in pointers if lo+BIAS<=(v&~1)<hi+BIAS],
        'external_pc_address_users':[x for x in literals if lo<=x['literal_file']<hi and not lo<=x['site']<hi],
        'outgoing_branch_candidates':[x for x in branches if lo<=x['site']<hi and not (x['target_file'] is not None and lo<=x['target_file']<hi)],
        'instructions':instructions})
database=(0x1f310,0x1f40c)
callback_table=(0x1f40c,0x1f418)
rows=[struct.unpack_from('<H16sHII',raw,database[0]+28*n) for n in range(9)]
assert rows[0][1][:4]==bytes.fromhex('0028e7fe')
callbacks=struct.unpack_from('<III',raw,callback_table[0])
assert callbacks==tuple(BIAS+x+1 for x in (0x7bf6,0x7ca0,0x7d0e))
ram_literals=[x for x in literals if x['kind']=='ldr' and 0x209dc0<=x['value']<0x209e80]
report={'schema':'whip.fee7-reference-survey.v1','inputs_sha256':inputs,
    'script_sha256':sha(Path(__file__).read_bytes()),'decoder_version':capstone.__version__,
    'exec_regions':EXEC_REGIONS,'halfword_positions':halfwords,'unaligned_pointer_positions':len(pointers),
    'spans':spans,'database_range':database,'callback_table_range':callback_table,
    'database_sha256':sha(raw[database[0]:database[1]]),'callback_words':callbacks,
    'table_pointer_candidates':[{'site':s,'value':v,'target_file':(v&~1)-BIAS} for s,v in pointers if database[0]+BIAS<=(v&~1)<callback_table[1]+BIAS],
    'table_pc_address_users':[x for x in literals if database[0]<=x['literal_file']<callback_table[1]],
    'selected_ram_literal_users':ram_literals,
    'setup_instructions':disassemble(0x76b8,0x76ee),
    'shared_callback_instructions':disassemble(0x6f28,0x7042),
    'approved_reclaimed_bytes':0,'reference_closure_verified':False,
    'hardware_access':False,'stock_file_modified':False,'flashable':False,
    'limits':['All-halfword candidates include data/second-half false positives.',
        'Whole-image stored absolute words do not cover computed, relative, ROM, upper-stack or retained pointers.',
        'Named functions are reference interpretations; callback table is exact stock evidence.',
        'No absence-of-reference result grants reclaim ownership; shared callback and literal pools are preserved.']}
assert inputs=={n:sha((ROOT/n).read_bytes()) for n in names}
with (OUT/'report.json').open('x') as f:
    json.dump(report,f,indent=2); f.write('\n')
print(json.dumps({'report':str(OUT/'report.json'),'sha256':sha((OUT/'report.json').read_bytes()),
 'spans':[{k:s[k] for k in ('name','lo','hi','bytes','incoming_branch_candidates','stored_pointer_candidates')} for s in spans],
 'table_pointer_candidates':report['table_pointer_candidates'],'ram_literal_users':ram_literals},indent=2))
