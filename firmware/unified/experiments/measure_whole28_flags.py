"""Finite whole-28 size experiments; all outputs are REJECTED, never firmware.

Rebuilds the exact current source objects, then measures short enums and a
different-frontend LTO/internalization trial while retaining every public
function with no reviewed in-set caller. Conditional holes remain the exact
nine historical, unowned intervals. Artificial strong bindings exist only so
the linker can measure size; they do not implement production contracts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from probe.owner_wait_budget import prior_inputs
from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot

CURRENT = ROOT / 'firmware/unified/research-20260925-control-owner-v2'
CURRENT_SHA = 'bef0a01786a01e84b4bc998c012375eb70612010013181755d4b423d63e005f0'
READ = ROOT / 'firmware/unified/research-20260925-discovery-read-v1'
READ_SHA = 'efc06a5a3540d82ad16239aceb54521b383931187ba124b9ce392e9d2a1d90ee'
BINDINGS = ROOT / 'firmware/unified/experiments/whole28_size_bindings.c'
ORIGINAL_SCRIPT = CURRENT / 'UNOWNED-unchanged-conditional.ld'
PLACED = frozenset(trial.PLACEMENTS)
EXPECTED_ROOTS = (
    '__aeabi_memcpy4', 'wa_cancelled', 'wa_fenced', 'wa_next', 'wa_observe',
    'wa_prepare', 'wa_sent', 'wc_optics_stopped', 'wc_physical_done',
    'wc_resume_prepared', 'wco_init', 'wco_open', 'wd_charging',
    'wd_reply_next', 'wd_reply_sent', 'wdi_encode', 'wdi_read', 'wdr_read',
    'wf_abandon', 'wf_complete', 'wf_init', 'wf_request', 'wg_stock_notify20',
    'wge_common', 'wgs_replace_fee7', 'wh_job_begin', 'wh_job_end',
    'wht_stop_scheduled', 'wim_post', 'wim_retire', 'wlg_receive',
    'wm_optics_allowed', 'woi_samples_io', 'wop_read', 'wrc_commit_hr',
    'ws_set_bounds', 'wuw_take', 'ww_pack_motion')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sections(path: Path) -> dict[str, int]:
    elf = trial._elf(path.read_bytes())
    return {name: (elf.get_section_by_name(name)['sh_size']
                   if elf.get_section_by_name(name) else 0)
            for name in ('.text', '.rodata', '.ARM.exidx')}


def public_roots(pins: dict[str, Path]) -> tuple[str, ...]:
    defined: dict[str, tuple[str, int]] = {}
    incoming = set()
    for owner, path in pins.items():
        elf = trial._elf(path.read_bytes())
        for symbol in elf.get_section_by_name('.symtab').iter_symbols():
            if (symbol['st_info']['type'] == 'STT_FUNC' and
                    symbol['st_info']['bind'] == 'STB_GLOBAL' and
                    symbol['st_shndx'] != 'SHN_UNDEF' and symbol['st_size']):
                defined[symbol.name] = (owner, symbol['st_size'])
    for path in pins.values():
        elf = trial._elf(path.read_bytes())
        symbols = elf.get_section_by_name('.symtab')
        for section in elf.iter_sections():
            if section['sh_type'] not in ('SHT_REL', 'SHT_RELA'):
                continue
            for relocation in section.iter_relocations():
                name = symbols.get_symbol(relocation['r_info_sym']).name
                if name in defined:
                    incoming.add(name)
    roots = tuple(sorted(set(defined) - incoming))
    if roots != EXPECTED_ROOTS:
        raise ValueError('public root inventory changed')
    return roots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--zig', required=True, type=Path)
    args = parser.parse_args()
    manifest, pins, prior = prior_inputs()
    current_path = CURRENT / 'budget-report.json'
    read_path = READ / 'proof-supplement.json'
    if sha(current_path) != CURRENT_SHA or sha(read_path) != READ_SHA:
        raise ValueError('reviewed parent changed')
    current, read = json.loads(current_path.read_text()), json.loads(read_path.read_text())
    for name in ('control_mailbox', 'stock_supervisor_wait', 'control_owner'):
        pins[name] = CURRENT / (name + '.o')
        if sha(pins[name]) != current['artifacts_sha256'][name + '.o']:
            raise ValueError('current owner artifact changed')
    for name, relative in {
        'stock_service_slot': 'executed-proof/stock-service-slot1/stock_service_slot.o',
        'stock_event_gate': 'executed-proof/stock-event-gate0/stock_event_gate.o',
        'stock_discovery_read': 'executed-proof/stock-discovery-read0/stock_discovery_read.o',
    }.items():
        pins[name] = READ / relative
        if sha(pins[name]) != read['artifacts_sha256'][relative]:
            raise ValueError('reviewed discovery artifact changed')
    if len(pins) != 28 or set(pins) - {p.stem for p in pins.values()}:
        raise ValueError('whole-28 object names changed')
    roots = public_roots(pins)
    sources = {name: ROOT / f'firmware/unified/{name}.c' for name in pins}
    paths = {str(p.relative_to(ROOT)): p for p in (*pins.values(), *sources.values(),
        BINDINGS, Path(__file__), ORIGINAL_SCRIPT, current_path, read_path, prior,
        ROOT / 'probe/owner_wait_budget.py', ROOT / 'whip/fwraw_relocation_trial.py',
        ROOT / 'whip/fwproof_guard.py')}
    for header in (ROOT / 'firmware/unified').glob('*.h'):
        paths[str(header.relative_to(ROOT))] = header
    inputs = InputSnapshot(paths)
    tools = InputSnapshot({'clang': Path('/usr/bin/clang'), 'zig': args.zig.resolve(),
                           'python': Path(sys.executable)})
    if tools.hashes != {n: manifest['tool_executables_sha256'][n] for n in tools.hashes}:
        raise ValueError('reviewed tools changed')
    if subprocess.check_output([args.zig, 'version'], text=True).strip() != '0.15.2':
        raise ValueError('reviewed Zig required')
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    artifacts: dict[str, str] = {}
    snapshots = [inputs, tools]

    def verify() -> None:
        for snapshot in snapshots:
            snapshot.verify()

    def capture(path: Path) -> None:
        key = str(path.relative_to(output))
        snapshots.append(InputSnapshot({key: path}))
        artifacts[key] = sha(path)

    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / 'cache'),
               ZIG_LOCAL_CACHE_DIR=str(output / 'local'))
    commands = 0

    def run(command: list[str], *, ok: bool = True) -> subprocess.CompletedProcess:
        nonlocal commands
        verify()
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        log = output / f'command-{commands:03}.json'; commands += 1
        log.write_text(json.dumps({'command': command, 'exit': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr}, indent=2) + '\n')
        capture(log)
        if (result.returncode == 0) is not ok:
            raise RuntimeError(result.stderr)
        return result

    flags = list(manifest['flags'])
    base_dirs = [output / 'baseline', output / 'baseline-repeat']
    short_dirs = [output / 'short-enums', output / 'short-enums-repeat']
    lto_dirs = [output / 'lto', output / 'lto-repeat']
    for directory in (*base_dirs, *short_dirs, *lto_dirs):
        directory.mkdir()
    # Exact current source reproduction, twice, before comparing variants.
    for name, source in sources.items():
        for directory in base_dirs:
            obj = directory / (name + '.o')
            run(['/usr/bin/clang', *flags, '-c', str(source), '-o', str(obj)])
            capture(obj)
            if obj.with_suffix('.su').exists():
                capture(obj.with_suffix('.su'))
        suffixes = ['.o'] + (['.su'] if (base_dirs[0] / (name + '.su')).exists() else [])
        if any((base_dirs[0] / (name + ext)).read_bytes() !=
               (base_dirs[1] / (name + ext)).read_bytes() for ext in suffixes):
            raise ValueError('baseline compile did not reproduce')
        if sha(base_dirs[0] / (name + '.o')) != sha(pins[name]):
            raise ValueError('current source no longer reproduces pinned object: ' + name)
    # Short enums fail an owned-RAM ABI assertion. Forced objects only quantify
    # the maximum compiler-size lead; they are never linked or behavior-tested.
    refusal = run(['/usr/bin/clang', *flags, '-fshort-enums', '-c',
                   str(sources['control_owner']), '-o', str(output / 'MUST-NOT-EXIST.o')], ok=False)
    if 'expression evaluates to \'868 == 880\'' not in refusal.stderr:
        raise ValueError('short-enum ABI refusal changed')
    forced = '-D_Static_assert(x,y)='
    for name, source in sources.items():
        for directory in short_dirs:
            obj = directory / (name + '.o')
            run(['/usr/bin/clang', *flags, '-fshort-enums', forced,
                 '-c', str(source), '-o', str(obj)])
            capture(obj)
            if obj.with_suffix('.su').exists():
                capture(obj.with_suffix('.su'))
        suffixes = ['.o'] + (['.su'] if (short_dirs[0] / (name + '.su')).exists() else [])
        if any((short_dirs[0] / (name + ext)).read_bytes() !=
               (short_dirs[1] / (name + ext)).read_bytes() for ext in suffixes):
            raise ValueError('short-enum compile did not reproduce')
    baseline_sections = Counter()
    short_sections = Counter()
    for name in pins:
        baseline_sections.update(sections(base_dirs[0] / (name + '.o')))
        short_sections.update(sections(short_dirs[0] / (name + '.o')))
    if dict(baseline_sections) != {'.text': 12404, '.rodata': 288, '.ARM.exidx': 1192}:
        raise ValueError('baseline sections changed')
    if dict(short_sections) != {'.text': 12332, '.rodata': 288, '.ARM.exidx': 1192}:
        raise ValueError('short-enum measurement changed')
    # Expand only the diagnostic append region so a failed fit can be measured.
    original = ORIGINAL_SCRIPT.read_text()
    marker = 'app (rx) : ORIGIN = 0x847ad0, LENGTH = 0x2530'
    if original.count(marker) != 1:
        raise ValueError('reviewed linker script changed')
    expanded = output / 'MEASUREMENT-ONLY-expanded.ld'
    expanded.write_text(original.replace(marker, 'app (rx) : ORIGIN = 0x847ad0, LENGTH = 0x5000'))
    capture(expanded)
    # Artificial binding is reproduced with each frontend. It includes the
    # 12-byte callback constant and tiny fake clock/placeholder code, but no
    # actual write/CCCD implementation or owned RAM.
    for directory in base_dirs:
        obj = directory / 'size-bindings.o'
        run(['/usr/bin/clang', *flags, '-c', str(BINDINGS), '-o', str(obj)])
        capture(obj); capture(obj.with_suffix('.su'))
    if any((base_dirs[0] / ('size-bindings' + ext)).read_bytes() !=
           (base_dirs[1] / ('size-bindings' + ext)).read_bytes() for ext in ('.o', '.su')):
        raise ValueError('baseline binding did not reproduce')
    retain_ld = [item for root in roots for item in ('-u', root)]
    baseline_elfs = []
    for index, directory in enumerate(base_dirs):
        target = output / f'REJECTED-baseline-{index}.elf'
        objects = [directory / (name + '.o') for name in pins] + [directory / 'size-bindings.o']
        run([str(args.zig), 'ld.lld', '-T', str(expanded), '-e', 'wd_init',
             '--build-id=none', '-z', 'max-page-size=4', *retain_ld,
             *map(str, objects), '-o', str(target)])
        capture(target); baseline_elfs.append(target)
    if baseline_elfs[0].read_bytes() != baseline_elfs[1].read_bytes():
        raise ValueError('baseline link did not reproduce')
    # Preserve all nine moved Apple-Clang objects byte-for-byte. Only append
    # units use the different Zig/LLVM frontend and LTO/internalization.
    zig_flags = ['-target', 'thumb-freestanding-eabi', '-mcpu=cortex_m0plus', '-mthumb',
                 '-ffreestanding', '-fno-builtin', '-Oz', '-std=c11', '-Wall', '-Wextra',
                 '-Werror', '-I', str(ROOT / 'firmware/unified'), '-flto']
    for index, directory in enumerate(lto_dirs):
        for name, source in sources.items():
            obj = directory / (name + '.o')
            if name in PLACED:
                shutil.copyfile(pins[name], obj)
            else:
                run([str(args.zig), 'cc', *zig_flags, '-c', str(source), '-o', str(obj)])
            capture(obj)
        binding = directory / 'size-bindings.o'
        run([str(args.zig), 'cc', *zig_flags, '-c', str(BINDINGS), '-o', str(binding)])
        capture(binding)
        target = output / f'REJECTED-lto-{index}.elf'
        retain_cc = ['-Wl,-u,' + root for root in roots]
        run([str(args.zig), 'cc', '-target', 'thumb-freestanding-eabi',
             '-mcpu=cortex_m0plus', '-mthumb', '-nostdlib', '-Wl,-T,' + str(expanded),
             # The stock image supplies the real entry. Pick an already-retained
             # external root so measurement does not preserve an extra API body.
             '-Wl,-e,wuw_take', '-Wl,--build-id=none', '-Wl,--gc-sections',
             '-Wl,-z,max-page-size=4', *retain_cc,
             *map(str, sorted(directory.glob('*.o'))), '-o', str(target)])
        capture(target)
    if (output / 'REJECTED-lto-0.elf').read_bytes() != (output / 'REJECTED-lto-1.elf').read_bytes():
        raise ValueError('LTO trial did not reproduce')

    def linked(path: Path) -> dict[str, int]:
        elf = trial._elf(path.read_bytes())
        text, unwind = (elf.get_section_by_name(n) for n in ('.text', '.ARM.exidx'))
        occupied = unwind['sh_addr'] + unwind['sh_size'] - 0x847AD0
        return {'append_text_bytes': text['sh_size'], 'linked_unwind_bytes': unwind['sh_size'],
                'append_occupied_bytes': occupied, 'configured_bytes': 9520,
                'over_bytes': occupied - 9520}

    baseline = linked(baseline_elfs[0])
    lto = linked(output / 'REJECTED-lto-0.elf')
    if baseline != {'append_text_bytes': 10828, 'linked_unwind_bytes': 16,
                    'append_occupied_bytes': 10844, 'configured_bytes': 9520, 'over_bytes': 1324}:
        raise ValueError('baseline link measurement changed')
    if lto != {'append_text_bytes': 10716, 'linked_unwind_bytes': 472,
               'append_occupied_bytes': 11188, 'configured_bytes': 9520, 'over_bytes': 1668}:
        raise ValueError('LTO link measurement changed')
    verify()
    report = {
        'schema': 'whip.rejected-whole28-flags.v1', 'inputs_sha256': inputs.hashes,
        'tools_sha256': tools.hashes, 'artifacts_sha256': artifacts,
        'exact_source_objects_reproduced': 28, 'public_no_inset_caller_roots': list(roots),
        'public_root_count': len(roots), 'public_root_text_bytes_before_lto': 3084,
        'baseline_input_sections': dict(baseline_sections), 'short_enum_input_sections': dict(short_sections),
        'short_enum_text_delta_bytes': short_sections['.text'] - baseline_sections['.text'],
        'short_enum_owner_bytes': {'required': 880, 'observed': 868},
        'short_enum_linked': False, 'short_enum_behavior_tested': False,
        'baseline_artificial_link': baseline, 'internalized_lto_artificial_link': lto,
        'lto_text_delta_bytes': lto['append_text_bytes'] - baseline['append_text_bytes'],
        'lto_unwind_delta_bytes': lto['linked_unwind_bytes'] - baseline['linked_unwind_bytes'],
        'lto_total_delta_bytes': lto['append_occupied_bytes'] - baseline['append_occupied_bytes'],
        'accepted_source_changed': False, 'accepted_objects_changed': False,
        'adopted': False, 'hardware_access': False, 'stock_bytes_written': 0,
        'flashable': False, 'whole_code_fit_proven': False, 'physical_bindings_implemented': False,
        'limits': 'Both links use an expanded MEASUREMENT-ONLY append region, nine exact unowned conditional placements and fake absolute bindings. Every current public function without an in-set relocation caller is retained, but that is not complete physical root closure. Missing write/CCCD callbacks are placeholders. Short enums violate the reviewed wco_owner ABI and save only72 input text bytes. Different-frontend append LTO saves112 linked text bytes but adds456 linked unwind bytes, growing total append occupancy344; it is rejected. No behavior, placement ownership, recovery, ring or image qualification.',
    }
    report_path = output / 'measurements.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    capture(report_path); verify()
    print(json.dumps({'archive': str(output), 'report_sha256': sha(report_path),
                      'baseline': baseline, 'lto': lto,
                      'short_enum_text_delta': report['short_enum_text_delta_bytes'],
                      'artifacts': len(artifacts)}))


if __name__ == '__main__':
    main()
