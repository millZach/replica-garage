"""Freeze an accepted assembly pass under accepted/<assembly>/NN/ and update build.json.

usage: python tools/accept.py <assembly> <version> [--project DIR] [--depends-on a,b]
                              [--seats FILE] [--build FILE] [--also-build FILE] [--force]

Copies src/<assembly>.py to accepted/<assembly>/<NN>/<assembly>.py, computes its SHA-256, writes
accepted/<assembly>/<NN>/manifest.json, and adds or updates the assembly in data/build.json (creating
build.json when absent). --also-build (repeatable or comma-separated, e.g. data/build-workshop.json)
updates every additional build list that already names the assembly ("one accept, every list").
--seats takes a JSON file holding either [{"part", "on"}, ...] or {"seats": [{"part", "on"}, ...]}.
If accepted/<assembly>/<NN>/ already exists with a different SHA-256, exits 2 unless --force is given.
Exit 0 on success, 2 on bad input.
"""
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_OK, load_json, run, save_json  # noqa: E402

USAGE = ('python tools/accept.py <assembly> <version> [--project DIR] [--depends-on a,b] '
         '[--seats FILE] [--build FILE] [--also-build FILE]')


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


def update_build_list(path, assembly, version, seats, add_if_missing=True):
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
            found = True
            break
    if not found:
        if not add_if_missing:
            return False
        entries.append({'assembly': assembly, 'version': version, 'seats': seats or []})
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
    ap.add_argument('--build')
    ap.add_argument('--also-build', action='append', default=[])
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

    src = os.path.join(project, 'src', assembly + '.py')
    if not os.path.isfile(src):
        raise BadInput('source module not found: %s' % src)
    deps = [d.strip() for d in a.depends_on.split(',') if d.strip()]
    if assembly in deps:
        raise BadInput('assembly %r cannot depend on itself' % assembly)
    seats = read_seats(a.seats if os.path.isabs(a.seats) else os.path.join(project, a.seats)) if a.seats else None

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
    update_build_list(main_build, assembly, version, seats, add_if_missing=True)
    updated = [os.path.relpath(main_build, project).replace(os.sep, '/')]

    extras = []
    for raw in a.also_build:
        extras.extend(x.strip() for x in raw.split(',') if x.strip())
    for ex in extras:
        p = ex if os.path.isabs(ex) else os.path.join(project, ex)
        if update_build_list(p, assembly, version, seats, add_if_missing=False):
            updated.append(os.path.relpath(p, project).replace(os.sep, '/'))

    print('ACCEPTED %s %s  sha256=%s  lists=%s' % (assembly, vdir, digest[:12], ', '.join(updated)))
    return EXIT_OK


if __name__ == '__main__':
    run(main)
