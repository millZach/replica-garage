"""Freeze an accepted assembly pass under accepted/<assembly>/NN/ and update build.json.

usage: python tools/accept.py <assembly> <version> [--project DIR] [--depends-on a,b]
                              [--seats FILE] [--seams FILE] [--build FILE] [--also-build FILE]
                              [--round DIR | --triage FILE] [--macro-fix] [--require-stage1] [--force]

Copies src/<assembly>.py to accepted/<assembly>/<NN>/<assembly>.py, computes its SHA-256, writes
accepted/<assembly>/<NN>/manifest.json, and adds or updates the assembly in data/build.json (creating
build.json when absent). --also-build (repeatable or comma-separated, e.g. data/build-workshop.json)
updates every additional build list that already names the assembly ("one accept, every list").
--seats takes a JSON file holding either [{"part", "on"}, ...] or {"seats": [{"part", "on"}, ...]}.
--seams takes a JSON file holding either [{"a", "b"}, ...] or {"pairs": [{"a", "b"}, ...]}.

Strict 2-stage "Macro First" Blind Judge gate:
  When --round <evidence/round-NN> (containing macro-triage.json) or --triage <file> is passed,
  accept.py validates the round's Stage 1 binary macro triage. If ANY of the 4 Stage 1 checks failed
  (lamp_shapes_angles, zero_daylight_leaks, smooth_roofline_greenhouse, flush_panel_alignment),
  accepting any detail/non-macro assembly (e.g. cabin, interior, hardware, wheels, decals, underbody)
  is BLOCKED with exit code 1 until Stage 1 passes. Macro assemblies (body, shell, front, rear,
  front_rear, glass — or --macro-fix) remain accept-able so builders can fix the macro faults, unless
  --require-stage1 is passed.

If accepted/<assembly>/<NN>/ already exists with a different SHA-256, exits 2 unless --force is given.
Exit 0 on success, 1 when blocked by Stage 1 macro triage, 2 on bad input.
"""
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, run, save_json  # noqa: E402

USAGE = ('python tools/accept.py <assembly> <version> [--project DIR] [--depends-on a,b] '
         '[--seats FILE] [--seams FILE] [--build FILE] [--also-build FILE] [--round DIR | --triage FILE]')

MACRO_ASSEMBLIES = frozenset({'body', 'shell', 'front', 'rear', 'front_rear', 'glass'})


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_seats(path):
    d = load_json(path, 'seats file')
    seats = d.get('seats') if isinstance(d, dict) else d
    if not isinstance(seats, list):
        raise BadInput('%s must hold a list of {"part", "on"} or {"seats": [...]}' % path)
    out = []
    for i, s in enumerate(seats):
        if not isinstance(s, dict) or not s.get('part') or not s.get('on'):
            raise BadInput('%s entry %d needs "part" and "on"' % (path, i + 1))
        out.append({'part': str(s['part']), 'on': str(s['on'])})
    return out


def read_seams(path):
    cfg = F.seams(load_json(path, 'seams file'), os.path.basename(path))
    out = []
    for p in cfg['pairs']:
        entry = {'a': str(p['a']), 'b': str(p['b'])}
        for k in ('name', 'kind', 'min_gap_mm', 'max_gap_mm', 'max_flush_mm', 'search_radius_mm',
                  'edge_group_a', 'edge_group_b'):
            if k in p and p[k] is not None:
                entry[k] = p[k]
        out.append(entry)
    return out


def check_macro_triage_gate(triage_path, assembly, macro_fix=False, require_stage1=False):
    """Validate macro-triage.json and return (allowed, failed_checks, score_cap)."""
    t = F.macro_triage(load_json(triage_path, 'macro triage file'), os.path.basename(triage_path))
    if t['passed']:
        return True, [], None
    failed = []
    for k in F.MACRO_TRIAGE_CHECKS:
        v = t['checks'][k]
        ok = v if isinstance(v, bool) else v['passed']
        if not ok:
            failed.append(k)
    cap = t.get('score_cap', F.MACRO_SCORE_CAP)
    if require_stage1:
        return False, failed, cap
    if macro_fix or assembly.lower() in MACRO_ASSEMBLIES:
        return True, failed, cap
    return False, failed, cap


def update_build_list(path, assembly, version, seats, seams=None, add_if_missing=True):
    if os.path.isfile(path):
        entries = F.build(load_json(path, os.path.basename(path)), os.path.basename(path))
    else:
        if not add_if_missing:
            return False
        entries = []
    found = False
    for e in entries:
        if e['assembly'] == assembly:
            e['version'] = version
            if seats is not None:
                e['seats'] = seats
            if seams is not None:
                e['seams'] = seams
            found = True
            break
    if not found:
        if not add_if_missing:
            return False
        rec = {'assembly': assembly, 'version': version, 'seats': seats or []}
        if seams is not None:
            rec['seams'] = seams
        entries.append(rec)
    F.build(entries, os.path.basename(path))
    save_json(path, entries)
    return True


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('assembly')
    ap.add_argument('version')
    ap.add_argument('--project', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--depends-on', default='')
    ap.add_argument('--seats')
    ap.add_argument('--seams')
    ap.add_argument('--build')
    ap.add_argument('--also-build', action='append', default=[])
    ap.add_argument('--round', help='evidence/round-NN folder containing macro-triage.json for Stage 1 gating')
    ap.add_argument('--triage', help='path to macro-triage.json for Stage 1 gating')
    ap.add_argument('--macro-fix', action='store_true',
                    help='allow accepting a fix pass for a failed Stage 1 macro check')
    ap.add_argument('--require-stage1', action='store_true',
                    help='block acceptance for any assembly unless Stage 1 macro triage passed')
    ap.add_argument('--force', action='store_true')
    a = ap.parse(argv)

    project = os.path.abspath(a.project)
    if not os.path.isdir(project):
        raise BadInput('project folder not found: %s' % project)
    assembly = a.assembly.strip()
    if not assembly or any(c in assembly for c in '/\\'):
        raise BadInput('invalid assembly name: %r' % a.assembly)
    try:
        version = int(a.version)
    except ValueError:
        raise BadInput('version must be an integer, got %r' % a.version)
    if version < 0:
        raise BadInput('version must be >= 0')

    if a.round and a.triage:
        raise BadInput('give --round or --triage, not both')
    triage_path = None
    if a.triage:
        triage_path = a.triage if os.path.isabs(a.triage) else os.path.join(project, a.triage)
    elif a.round:
        rnd = a.round if os.path.isabs(a.round) else os.path.join(project, a.round)
        if not os.path.isdir(rnd):
            raise BadInput('round folder not found: %s' % a.round)
        triage_path = os.path.join(rnd, 'macro-triage.json')
    if triage_path:
        allowed, failed_checks, score_cap = check_macro_triage_gate(
            triage_path, assembly, macro_fix=a.macro_fix, require_stage1=a.require_stage1
        )
        if not allowed:
            print('BLOCKED BY STAGE 1 MACRO TRIAGE: %s cannot be accepted while Stage 1 failed (%s); '
                  'scores are capped at %g/100 until all 4 macro checks pass' % (
                      assembly, ', '.join(failed_checks), score_cap))
            return EXIT_GATE
        if failed_checks:
            print('NOTE Stage 1 macro triage failed (%s, score cap %g/100); accepting macro fix pass for %s' % (
                ', '.join(failed_checks), score_cap, assembly))

    src = os.path.join(project, 'src', assembly + '.py')
    if not os.path.isfile(src):
        raise BadInput('source module not found: %s' % src)
    deps = [d.strip() for d in a.depends_on.split(',') if d.strip()]
    if assembly in deps:
        raise BadInput('assembly %r cannot depend on itself' % assembly)
    seats = read_seats(a.seats if os.path.isabs(a.seats) else os.path.join(project, a.seats)) if a.seats else None
    seams_list = read_seams(a.seams if os.path.isabs(a.seams) else os.path.join(project, a.seams)) if a.seams else None

    vdir = '%02d' % version
    dest_dir = os.path.join(project, 'accepted', assembly, vdir)
    dest_mod = os.path.join(dest_dir, assembly + '.py')
    digest = sha256(src)
    if os.path.isfile(dest_mod) and not a.force:
        if sha256(dest_mod) != digest:
            raise BadInput('accepted/%s/%s/%s.py already exists with a different hash (use --force to replace)'
                           % (assembly, vdir, assembly))
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copyfile(src, dest_mod)
    man = F.manifest({'assembly': assembly, 'version': version, 'sha256': digest, 'depends_on': deps},
                     assembly, version, 'accepted/%s/%s/manifest.json' % (assembly, vdir))
    save_json(os.path.join(dest_dir, 'manifest.json'), man)

    main_build = a.build or os.path.join(project, 'data', 'build.json')
    if not os.path.isabs(main_build):
        main_build = os.path.join(project, main_build)
    update_build_list(main_build, assembly, version, seats, seams=seams_list, add_if_missing=True)
    updated = [os.path.relpath(main_build, project).replace(os.sep, '/')]

    extras = []
    for raw in a.also_build:
        extras.extend(x.strip() for x in raw.split(',') if x.strip())
    for ex in extras:
        p = ex if os.path.isabs(ex) else os.path.join(project, ex)
        if update_build_list(p, assembly, version, seats, seams=seams_list, add_if_missing=False):
            updated.append(os.path.relpath(p, project).replace(os.sep, '/'))

    print('ACCEPTED %s %s  sha256=%s  lists=%s' % (assembly, vdir, digest[:12], ', '.join(updated)))
    return EXIT_OK


if __name__ == '__main__':
    run(main)
