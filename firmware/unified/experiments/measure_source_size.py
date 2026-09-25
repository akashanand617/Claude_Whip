"""Archive a finite, REJECTED source-size trial. No ELF, image or device I/O.

Compiles each retained design twice with the accepted ARM compiler/flags.
This measures input sections and local stack, NOT behavior or physical stack.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from probe.owner_wait_budget import prior_inputs
from whip.fwproof_guard import InputSnapshot
from whip.fwraw_relocation_trial import _elf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--frames', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest, pins, _ = prior_inputs()
    sources = {
        'baseline': ROOT / 'firmware/unified/fresh_source.c',
        'preflight': args.preflight,
        'frames': args.frames,
        'outlined': ROOT / 'firmware/unified/experiments/fresh_source_split.c',
        'bucket': ROOT / 'firmware/unified/experiments/fresh_source_bucket.c',
        'headroom': ROOT / 'firmware/unified/experiments/fresh_source_headroom.c',
    }
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(sources['baseline']) == manifest['inputs_sha256']['firmware/unified/fresh_source.c']
    expected = {
        'preflight': 'a4d1a627a9e08066438edb5dbc19b3190652e2a69548e422c31b544190c8ef00',
        'outlined': '00d645b7cab9cd6d2fb82d900f806a99faa08d57d228ac12bf8e755c582e9519',
        'headroom': '5dc26f7e2dccaf085f0e71c39472ec66621b0a753108014f411ec69c76f07f44',
    }
    for name, digest in expected.items():
        assert sha(sources[name]) == digest, name
    paths = {str(p.absolute()): p for p in (*sources.values(), *pins.values(), Path(__file__),
        ROOT / 'firmware/unified/fresh_source.h', ROOT / 'firmware/unified/sample_tap.h',
        ROOT / 'probe/owner_wait_budget.py', ROOT / 'whip/fwraw_relocation_trial.py',
        ROOT / 'whip/fwproof_guard.py')}
    inputs = InputSnapshot(paths)
    tools = InputSnapshot({'clang': Path('/usr/bin/clang'), 'python': Path(sys.executable)})
    assert tools.hashes == {n: manifest['tool_executables_sha256'][n] for n in tools.hashes}
    output = args.output.absolute()
    output.mkdir(exist_ok=False)
    (output / 'sources').mkdir()
    captured = [inputs, tools]
    artifacts = {}

    def verify():
        for snapshot in captured:
            snapshot.verify()

    def snapshot(path):
        relative = str(path.relative_to(output))
        captured.append(InputSnapshot({relative: path}))
        artifacts[relative] = sha(path)

    measurements = {}
    for name, source in sources.items():
        verify()
        archived = output / 'sources' / (name + '.c')
        shutil.copyfile(source, archived)
        assert sha(archived) == sha(source)
        snapshot(archived)
        pair = [output / (name + suffix) for suffix in ('.o', '-repeat.o')]
        for obj in pair:
            verify()
            command = ['/usr/bin/clang', *manifest['flags'], '-c', str(archived), '-o', str(obj)]
            result = subprocess.run(command, capture_output=True, text=True)
            log = obj.with_suffix('.command.json')
            log.write_text(json.dumps({'command': command, 'exit': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}, indent=2) + '\n')
            snapshot(log)
            assert result.returncode == 0, result.stderr
            snapshot(obj); snapshot(obj.with_suffix('.su'))
        assert all(pair[0].with_suffix(ext).read_bytes() == pair[1].with_suffix(ext).read_bytes()
                   for ext in ('.o', '.su'))
        elf = _elf(pair[0].read_bytes())
        sections = {s.name: s['sh_size'] for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_size']}
        assert set(sections) == {'.text', '.ARM.exidx'}  # No added constants or static RAM.
        stack = {}
        for line in pair[0].with_suffix('.su').read_text().splitlines():
            label, size, kind = line.split('\t')
            assert kind == 'static'
            stack[label.rsplit(':', 1)[-1]] = int(size)
        measurements[name] = {'allocated_sections': sections, 'input_bytes': sum(sections.values()),
            'local_stack_bytes': stack,
            'functions': {s.name: s['st_size'] for s in elf.get_section_by_name('.symtab').iter_symbols()
                          if s['st_info']['type'] == 'STT_FUNC' and s['st_size']},
            'object': pair[0].name, 'adopted': False}
    assert {n: m['input_bytes'] for n, m in measurements.items()} == {
        'baseline': 1060, 'preflight': 1100, 'frames': 1096,
        'outlined': 1070, 'bucket': 1060, 'headroom': 1100}
    verify()
    result = {
        'schema': 'whip.rejected-fresh-source-size.v1', 'compiler_flags': manifest['flags'],
        'inputs_sha256': inputs.hashes, 'tools_sha256': tools.hashes,
        'artifacts_sha256': artifacts, 'measurements': measurements,
        'accepted_source_changed': False, 'adopted': False, 'hardware_access': False,
        'flashable': False, 'elf_linked': False, 'differential_tests_run': False,
        'whole28_append_lower_bound_unchanged': 10798, 'configured_append_bytes': 9520,
        'headroom_zero_period_caveat': 'Positive validated minimum period required for equivalence. Original C divides by zero on corrupted min0; pinned ARM helper returns0. Multiplied candidate faults instead. No universal corrupted-state equivalence claimed.',
        'limits': 'Input section/local-stack measurements only. No accepted candidate, behavioral proof, observed nested stack, physical stack headroom, memory ownership or full linked fit. Five finite designs rejected before expensive differential acceptance. Existing whole28 budget unchanged, not re-linked here. No safety policy, queue, feature, core pin or ring image changed.',
    }
    report = output / 'measurements.json'
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    snapshot(report); verify()
    print(json.dumps({'archive': str(output), 'report_sha256': sha(report),
                      'measurements': {n: m['input_bytes'] for n, m in measurements.items()}}))


if __name__ == '__main__':
    main()
