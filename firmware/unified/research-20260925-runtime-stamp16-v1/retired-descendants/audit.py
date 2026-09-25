"""Fixed retired-root descendant survey: scratch report, never image/placement."""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
import struct
import sys
import capstone
from capstone.arm import ARM_OP_IMM

ROOT=Path('/Users/akashanand/Claude_Whip')
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from whip.fwindicator import branch_candidate

input_names=['firmware/rt02cr-stock-3.12.02.bin','whip/fwindicator.py',
 'whip/fwretirement.py','whip/fwraw_relocation_trial.py',
 'docs/UNIFIED_RAW_RETIREMENT.md','docs/UNIFIED_DIAGNOSTIC_RETIREMENT.md',
 'docs/UNIFIED_INDICATOR_RETIREMENT.md','docs/UNIFIED_STOCK_RETIREMENT.md']
sha=lambda raw:hashlib.sha256(raw).hexdigest()
inputs={n:sha((ROOT/n).read_bytes()) for n in input_names}
data=(ROOT/input_names[0]).read_bytes()
assert len(data)==138016
assert sha(data)=='b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0'
BIAS=0x825fb0
regions=[(0x450,0x20cc8,BIAS+0x450),(0x20cc8,0x21578,0x207c00),
         (0x21a58,0x21b20,0x20e734)]
roots=[(0x1e4a,0x1f42),(0x1f70,0x2348),(0x48c6,0x48e8),
       (0x4910,0x4924),(0x4b02,0x4cbc),(0x3ac4,0x3de8)]
inside=lambda value,spans:any(a<=value<b for a,b in spans)
decoder=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB|capstone.CS_MODE_MCLASS)
decoder.detail=True

branches=[];pc_users=[];halfwords=0
for lo,hi,pc in regions:
    for offset in range(lo,hi-1,2):
        halfwords+=1
        address=pc+offset-lo
        candidate=branch_candidate(data,offset,address)
        if candidate and (candidate[0]!='bl' or offset+4<=hi):
            branches.append({'site':offset,'kind':candidate[0],'runtime_target':candidate[1]})
        first=struct.unpack_from('<H',data,offset)[0]
        if first&0xf800 in (0x4800,0xa000):
            pc_users.append({'site':offset,'kind':'ldr-literal' if first&0xf800==0x4800 else 'adr',
                             'runtime_target':((address+4)&~3)+4*(first&0xff)})
pointers=[(offset,struct.unpack_from('<I',data,offset)[0]) for offset in range(len(data)-3)]

def scan(name,lo,hi):
    decoded=list(decoder.disasm(data[lo:hi],BIAS+lo))
    assert sum(i.size for i in decoded)==hi-lo,(name,'noncontinuous decode')
    incoming=[]
    for r in branches:
        if BIAS+lo<=r['runtime_target']<BIAS+hi and not lo<=r['site']<hi:
            # Independent instruction decoder agrees on each incoming candidate.
            region=next(x for x in regions if x[0]<=r['site']<x[1])
            address=region[2]+r['site']-region[0]
            i=next(decoder.disasm(data[r['site']:r['site']+4],address),None)
            assert i is not None and i.operands[0].type==ARM_OP_IMM
            assert i.operands[0].imm==r['runtime_target']
            incoming.append({**r,'target_file':r['runtime_target']-BIAS})
    calls=[];external_branches=[];literals=[]
    for i in decoded:
        site=i.address-BIAS
        if i.mnemonic=='bl' and i.operands[0].type==ARM_OP_IMM:
            target=i.operands[0].imm
            calls.append({'site':site,'runtime_target':target,'target_file':target-BIAS,
              'other_immediate_entry_candidates':[r for r in branches if r['runtime_target']==target and not lo<=r['site']<hi]})
        if i.mnemonic.startswith('b') and i.operands[0].type==ARM_OP_IMM:
            target=i.operands[0].imm
            if i.mnemonic!='bl' and not BIAS+lo<=target<BIAS+hi:
                external_branches.append({'site':site,'runtime_target':target,'target_file':target-BIAS})
        for r in pc_users:
            if r['site']==site:
                off=r['runtime_target']-BIAS
                literals.append({**r,'target_file':off,'word':int.from_bytes(data[off:off+4],'little') if 0<=off<=len(data)-4 else None})
    return {'name':name,'file_start':lo,'file_end_exclusive':hi,'bytes':hi-lo,
            'sha256':sha(data[lo:hi]),'instructions':len(decoded),'incoming_candidates':incoming,
            'stored_pointer_candidates':[{'site':s,'value':v,'target_file':(v&~1)-BIAS} for s,v in pointers if BIAS+lo<=v&~1<BIAS+hi],
            'external_pc_relative_users':[r for r in pc_users if BIAS+lo<=r['runtime_target']<BIAS+hi and not lo<=r['site']<hi],
            'calls':calls,'external_branches':external_branches,'literal_loads_and_adr':literals}

new_specs=[('indicator_brightness_wrapper',0xf812,0xf824),
 ('indicator_busy_getter',0xf92e,0xf934),('indicator_driver_entry',0x11246,0x11364),
 ('indicator_register_programmer',0x121e8,0x1222c)]
new_spans=[(lo,hi) for _,lo,hi in new_specs]
new=[scan(*s) for s in new_specs]
for r in new:
    assert not r['stored_pointer_candidates'] and not r['external_pc_relative_users']
    assert all(inside(x['site'],roots+new_spans) for x in r['incoming_candidates'])
assert [(x['site'],x['target_file']) for x in new[2]['external_branches']]==[(0x11292,0x10e8a),(0x11362,0x10e8a)]

# Already-retired bodies NOT occupied by the nine existing trial placements.
# These are planning alternatives only; no linker script is generated/edited.
leftovers=[('brightness_body_tail',0x3b50,0x3b78),('pattern_request_tail',0x3c9c,0x3ca8),
 ('indicator_cancel_body',0x3cb0,0x3cd0),('custom_pattern_body',0x3cd8,0x3d34),
 ('timed_pattern_body',0x3d3c,0x3d9c),('brightness_request_body',0x3da4,0x3dc0),
 ('active_query_tail',0x3dc4,0x3dc8),('pattern_cancel_body',0x3dcc,0x3de8),
 ('bf_prefix_existing_unused_allowance',0x48cc,0x48e8),('bf_tail_existing_unused_allowance',0x4910,0x4924)]
unused=[scan(*s) for s in leftovers]
for r in unused:
    assert not r['stored_pointer_candidates']
    assert all(x['site']==0x3aba for x in r['external_pc_relative_users']), (r['name'],r['external_pc_relative_users'])
    assert all(inside(x['site'],roots) for x in r['incoming_candidates'])
assert data[0x3ab8:0x3abc]==bytes.fromhex('e5c3b2a1')
assert data[0x3aa4:0x3aa6]==bytes.fromhex('f8bd')
literal_users=[r['site'] for r in pc_users if r['runtime_target']==BIAS+0x3ab8 and r['kind']=='ldr-literal']
assert literal_users==[0x3806,0x381a]

raw_specs=[('raw_accumulator_clear',0xdf40,0xdf58),('raw_accumulator_second_get',0xdf58,0xdf60),
 ('raw_accumulator_first_get',0xdf60,0xdf68),('raw_halfword_get',0xdfce,0xdfd4),
 ('raw_halfword_clear',0xdfd4,0xdfdc)]
raw=[scan(*s) for s in raw_specs]
for r in raw:
    assert not r['stored_pointer_candidates'] and not r['external_pc_relative_users']
    assert all(inside(x['site'],roots) for x in r['incoming_candidates'])

def allowance(row):
    lo=(row['file_start']+4+3)&~3;hi=row['file_end_exclusive']&~3
    return {'name':row['name'],'after_four_byte_entry_allowance':[lo,hi],
            'aligned_bytes':max(0,hi-lo)}

excluded=[scan('shared_indicator_stop',0xf7ba,0xf7ce),
 scan('retained_stop_alias',0xf94c,0xf94e),scan('shared_driver_epilogue',0x10e8a,0x10e8e),
 scan('retained_neighbor_register_programmer',0x1222c,0x12268)]
new_allowances=[allowance(x) for x in new];raw_allowances=[allowance(x) for x in raw]
assert sum(x['aligned_bytes'] for x in new_allowances)==356
assert sum(x['aligned_bytes'] for x in raw_allowances)==32
assert sum(x['bytes'] for x in unused)==380
assert inputs=={n:sha((ROOT/n).read_bytes()) for n in input_names}
result={'schema':'scratch.retired-descendants.v1','inputs_sha256':inputs,
 'decoder_version':capstone.__version__,'script_sha256':sha(Path(__file__).read_bytes()),
 'mapped_scan_regions':regions,'halfword_branch_and_pc_relative_candidate_positions':halfwords,
 'whole_image_unaligned_le32_positions':len(pointers),'new_descendant_spans':new,
 'old_root_unoccupied_body_spans':unused,'previously_known_raw_helpers':raw,
 'reviewed_pc_relative_false_candidate':{
     'site':0x3aba,'apparent_target_file':0x3d84,
     'classification':'ADR-like upper halfword of literal data, not a reviewed instruction',
     'literal_word_file':0x3ab8,'literal_word_value':0xa1b2c3e5,
     'confirmed_literal_load_sites':literal_users,'preceding_function_return':0x3aa4,
     'literal_pool_preserved':True},
 'excluded_shared_examples':excluded,'new_descendant_allowances':new_allowances,
 'known_raw_helper_allowances':raw_allowances,
 'totals':{'new_descendant_instruction_bytes':sum(x['bytes'] for x in new),
           'new_descendant_aligned_bytes_after_entry_allowances':356,
           'unoccupied_indicator_bodies':332,'existing_unused_bf_allowances':48,
           'known_raw_helpers_after_entry_allowances':32,'enumerated_extra_allowances':768,
           'current_append_lower_bound_over':1090,'still_short_before_extra_costs':322},
 'approved_reclaimed_bytes':0,'entry_indirect_closure_proven':False,
 'physical_shutdown_or_retention_proven':False,'actual_placement_attempted':False,
 'firmware_or_source_or_linker_changed':False,'hardware_access':False,
 'limits':['Immediate all-halfword candidates and whole-image absolute pointers are not computed/relative/ROM/patch/retained-entry closure.',
           'PC-relative candidates include possible data or wide-instruction-second-half false positives; their absence is not pointer analysis.',
           'Original shared driver epilogue, Health helpers, state/literal pools and ordinary motion/DFU bodies remain excluded.',
           'Four-byte return stubs are only a conservative size allowance, not reviewed new-stub semantics or an authorization.',
           'Conditional totals are not a successful link, ownership, future stack headroom, physical Health equivalence, or an exhaustive upper bound on all possible code changes.']}
(OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'report':str(OUT/'report.json'),'sha256':sha((OUT/'report.json').read_bytes()),
                  'totals':result['totals'],'halfword_positions':halfwords,'pointer_positions':len(pointers),
                  'new_spans':[{k:x[k] for k in ('name','file_start','file_end_exclusive','bytes','sha256','incoming_candidates','external_branches')} for x in new]},indent=2))
