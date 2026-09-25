"""Verify explicit FEE7-survey interpretations without executing ring code."""
from pathlib import Path
import hashlib
import json
import struct
import capstone

ROOT=Path('/Users/akashanand/Claude_Whip')
OUT=Path(__file__).parent
sha=lambda b:hashlib.sha256(b).hexdigest()
stock=ROOT/'firmware/rt02cr-stock-3.12.02.bin'
raw=stock.read_bytes()
assert sha(raw)=='b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0'
survey_path=OUT/'report.json'
assert sha(survey_path.read_bytes())=='9ef0bfe3a30ad84de3bd8981268574424eb7b564ef0535d69ee4b05f7a16aa6a'
survey=json.loads(survey_path.read_text())
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB|capstone.CS_MODE_MCLASS)
md.detail=True
bias=0x825fb0
u32=lambda off:struct.unpack_from('<I',raw,off)[0]
assert u32(0x7778)==0x209e21 and raw[0x76c8:0x76ca].hex()=='a41f'
assert raw[0x76e2:0x76e4].hex()=='e070'
assert u32(0x705c)==0x209df4
assert raw[0x6f36:0x6f3e].hex()=='494bdd78aa4256d1'
assert raw[0x6fec:0x6ff2].hex()=='1b799a4225d1'
assert 0x209e21-6+3==0x209e1e
assert 0x209df4+3==0x209df7 and 0x209df4+4==0x209df8
assert u32(0x7788)==bias+0x6f29
assert u32(0x7da4)==0x209e4c
assert raw[0x7d96:0x7d9c].hex()=='0348001f8460'
assert 0x209e4c-4+8==0x209e50
false=list(md.disasm(raw[0x7e8e:0x7e92],bias+0x7e8e))
assert len(false)==1 and false[0].size==4 and false[0].mnemonic=='bl'
assert false[0].operands[0].imm==0x13146
add=next(x for x in survey['spans'] if x['name']=='fee7_add')
assert [(x['site'],x['kind']) for x in add['incoming_branch_candidates']]==[(0x76de,'bl'),(0x7e90,'bcc')]
assert sum(x['bytes'] for x in survey['spans'])==526
assert all(not x['incoming_branch_candidates'] for x in survey['spans'][:-1])
assert [x['stored_pointer_candidates'] for x in survey['spans']][3:6]==[
    [{'site':0x1f40c,'value':bias+0x7bf7}],
    [{'site':0x1f410,'value':bias+0x7ca1}],
    [{'site':0x1f414,'value':bias+0x7d0f}]]
assert all(not x['external_pc_address_users'] for x in survey['spans'])
assert raw[0x7498:0x74a8].hex()=='b74c032020706070e725a570fe26e670'
assert u32(0x7778)==0x209e21
# r4=0x209e21; these stores produce an AD structure: len3,type3,uuidFEE7.
advertisement=[3,3,0xe7,0xfe]
result={'schema':'whip.fee7-checked-findings.v1',
 'survey_sha256':sha(survey_path.read_bytes()),'script_sha256':sha(Path(__file__).read_bytes()),
 'stock_sha256':sha(raw),'decoder_version':capstone.__version__,
 'setup_old_id':0x209e1e,'shared_callback_selectors':[0x209df7,0x209df8],
 'selectors_are_setup_slot':False,'selector_copy_relationship_proven':False,
 'fee7_application_callback_slot':0x209e50,
 'known_setup_entry_call':0x76de,'callback_table_entries':[0x1f40c,0x1f410,0x1f414],
 'rejected_branch_candidate':{'site':0x7e90,'actual_instruction_start':0x7e8e,
     'actual_target':0x13146,'reason':'second halfword of retained UART delay BL'},
 'advertisement_builder':{'file_span':[0x7498,0x74a8],'ram_start':0x209e21,
     'first_four_bytes':advertisement,'service_removed_does_not_remove_advertising':True},
 'gross_candidate_instruction_bytes':526,'gross_database_bytes':252,'gross_callback_table_bytes':12,
 'gross_survey_total_bytes':790,'approved_reclaimed_bytes':0,
 'preserve':['shared callback0x6f28..0x7042','literal pool0x7da2..0x7dc4',
             'stock Stack/ROM wrappers','Health, UART, DFU, DIS and HID paths'],
 'arithmetic_only':{'accepted26_input_excess':1154,'pending_callback_constant_bytes':12,
    'optimistic_remaining_excess_even_if_all790_usable':376,
    'limits':'No actual placement; excludes final alignment/unwind and remaining binding code. New table240 already in26-object lower bound.'},
 'reference_closure_verified':False,'hardware_access':False,'flashable':False}
with (OUT/'findings.json').open('x') as f:
 json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({'findings':str(OUT/'findings.json'),'sha256':sha((OUT/'findings.json').read_bytes()),
 'gross_bytes':790,'approved_bytes':0,'all_assertions_passed':True}))
