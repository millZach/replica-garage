"""Apply accepted patches, in order, to a base scene and save the merged scene.          (runs in Blender)

usage: blender -b <base.blend> --python tools/merge.py -- --out merged.blend accepted/<area>-NN [...]
       [--force]

Takes only frozen folders: each must be accepted/<area>-NN/ holding apply.py and manifest.json. manifest.json:
  {"area": "doors", "number": 3,
   "sha256": {"apply.py": "<hex>", "<every other file in the folder>": "<hex>"},
   "requires": ["accepted folder names that must be merged earlier"],
   "touches": ["names of the objects the patch changes"]}
Every file in the folder (other than manifest.json) must be listed with its SHA-256, and every hash must match,
before anything is applied. "requires" must appear earlier in the list. Two patches that touch the same object
need the later one to require the earlier one, so overlapping changes are ordered on purpose.
apply.py runs inside this Blender session with the folder as its working directory. It changes bpy.data and must
not save; when it defines apply(folder) that function is called after the module runs. A patch that raises stops
the merge and nothing is saved.
Writes the merged scene to --out (never over the base scene; an existing file only with --force) and
<out>.json with each step, its hashes and how long it took.
Exit 1 when a hash does not match, a file is unlisted, an order rule is broken or a step fails; 2 on bad input.
"""
import hashlib
import json
import os
import re
import runpy
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = 'blender -b <base.blend> --python tools/merge.py -- --out merged.blend accepted/<area>-NN [...] [--force]'
FOLDER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*-\d{2,}$')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def folder_files(folder):
    out = []
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for n in files:
            rel = os.path.relpath(os.path.join(d, n), folder).replace(os.sep, '/')
            if rel != 'manifest.json':
                out.append(rel)
    return sorted(out)


def check(folders):
    """Validate every folder before anything runs. Returns (steps, problems that fail the merge)."""
    steps, problems = [], []
    for f in folders:
        f = os.path.abspath(f)
        name = os.path.basename(f.rstrip('/\\'))
        if not os.path.isdir(f):
            raise BadInput('patch folder not found: %s' % f)
        if os.path.basename(os.path.dirname(f)) != 'accepted' or not FOLDER.match(name):
            raise BadInput('%s is not a frozen accepted/<area>-NN folder' % f)
        if not os.path.isfile(os.path.join(f, 'apply.py')):
            raise BadInput('%s has no apply.py' % name)
        man = load_json(os.path.join(f, 'manifest.json'), 'manifest of %s' % name)
        hashes = man.get('sha256') if isinstance(man, dict) else None
        if not isinstance(hashes, dict) or 'apply.py' not in hashes:
            raise BadInput('manifest of %s needs "sha256" with the hash of apply.py' % name)
        got = {}
        for rel in folder_files(f):
            got[rel] = sha256(os.path.join(f, rel))
            if rel not in hashes:
                problems.append('%s: %s is not listed in the manifest (the folder is not frozen)' % (name, rel))
            elif str(hashes[rel]).lower() != got[rel]:
                problems.append('%s: %s does not match its SHA-256' % (name, rel))
        for rel in hashes:
            if rel not in got:
                problems.append('%s: %s is listed but missing' % (name, rel))
        req, touches = man.get('requires', []), man.get('touches', [])
        if not isinstance(req, list) or not isinstance(touches, list):
            raise BadInput('manifest of %s: "requires" and "touches" must be lists' % name)
        steps.append(dict(folder=f, name=name, sha256=got, requires=[str(r) for r in req],
                          touches=[str(t) for t in touches]))
    seen = []
    for s in steps:
        for r in s['requires']:
            if r not in seen:
                problems.append('%s requires %s, which is not merged before it' % (s['name'], r))
        seen.append(s['name'])
    for i, s in enumerate(steps):
        for e in steps[:i]:
            common = set(s['touches']) & set(e['touches'])
            if common and e['name'] not in s['requires']:
                problems.append('%s and %s both change %s; %s must require %s'
                                % (e['name'], s['name'], ', '.join(sorted(common)), s['name'], e['name']))
    if len({s['name'] for s in steps}) != len(steps):
        problems.append('a folder is listed twice')
    return steps, problems


def apply_step(s):
    cwd, argv = os.getcwd(), sys.argv
    os.chdir(s['folder'])
    sys.argv = [os.path.join(s['folder'], 'apply.py')]
    try:
        g = runpy.run_path(os.path.join(s['folder'], 'apply.py'), run_name='__replica_patch__')
        if callable(g.get('apply')):
            g['apply'](s['folder'])
    finally:
        os.chdir(cwd)
        sys.argv = argv


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('folders', nargs='+')
    a = ap.parse(argv)
    bpy = B.bpy
    base = bpy.data.filepath
    out = os.path.abspath(a.out)
    if not base:
        raise BadInput('open the base scene: blender -b <base.blend> --python tools/merge.py -- ...')
    if os.path.normcase(out) == os.path.normcase(os.path.abspath(base)):
        raise BadInput('--out must not be the base scene')
    if os.path.exists(out) and not a.force:
        raise BadInput('%s exists; pass --force to replace it' % out)
    steps, problems = check(a.folders)
    log = dict(base=os.path.abspath(base), out=out, steps=[], problems=problems)
    if problems:
        for p in problems:
            print('STOP', p)
        log['passed'] = False
        save_json(out + '.json', log)
        return EXIT_GATE
    for s in steps:
        t0 = time.monotonic()
        entry = dict(name=s['name'], sha256=s['sha256'], requires=s['requires'], touches=s['touches'])
        try:
            apply_step(s)
        except BaseException as e:            # a patch calling sys.exit is a failed step too
            entry.update(status='failed', error='%s: %s' % (type(e).__name__, e), traceback=traceback.format_exc(),
                         seconds=round(time.monotonic() - t0, 2))
            log['steps'].append(entry)
            log['passed'] = False
            save_json(out + '.json', log)
            print('FAILED at %s: %s' % (s['name'], entry['error']))
            return EXIT_GATE
        entry.update(status='applied', seconds=round(time.monotonic() - t0, 2))
        log['steps'].append(entry)
        print('applied', s['name'])
    bpy.context.scene['replica_garage_merged'] = json.dumps([dict(name=s['name'], apply_sha256=s['sha256']['apply.py'])
                                                             for s in steps])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, copy=True)
    log['passed'] = os.path.isfile(out)
    save_json(out + '.json', log)
    print('MERGED', out)
    return EXIT_OK if log['passed'] else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
