"""Build the vehicle from the accepted modules, in order, in a clean scene.               (runs in Blender)

usage: blender -b --python tools/assemble.py -- [--project DIR] [--build data/build.json] [--working ASSEMBLY]
       [--look NAME] [--out FILE]

--project defaults to the folder above this tools/ folder. build.json is a list of
{"assembly": name, "version": NN, "seats": [...]} in build order. Each entry's module is
accepted/<assembly>/<NN>/<assembly>.py, and its manifest.json there gives "sha256" of that file and
"depends_on" (assemblies whose surface it asks for). Every hash is checked before anything is built, and every
assembly in depends_on must come earlier in the list.
--working <assembly> takes that module from src/<assembly>.py instead of its accepted version (or adds it after
the listed ones if it is not in the list yet) and saves to out/work-<assembly>.blend.
Each module's build(ctx) runs with the kit's Context (tools/kit.py): vehicle.json, the look (--look, default the
proof look in data/finishes.json) and data/parts.json. The scene is saved to --out (default out/vehicle.blend),
with <out>.json beside it: each module, its hash, the objects it registered and any warnings.
Exit 1 on a hash mismatch, an order rule broken or any module error (nothing is saved); 2 on bad input.
"""
import hashlib
import importlib.util
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import kit  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b --python tools/assemble.py -- [--project DIR] [--build data/build.json] '
         '[--working ASSEMBLY] [--look NAME] [--out FILE]')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def version_dir(v):
    try:
        return '%02d' % int(v)
    except (TypeError, ValueError):
        raise BadInput('version %r is not a number' % (v,))


def plan(project, build, working):
    steps, problems = [], []
    names = []
    for i, e in enumerate(build):
        if not isinstance(e, dict) or 'assembly' not in e or 'version' not in e:
            raise BadInput('build entry %d needs "assembly" and "version"' % (i + 1))
        a = str(e['assembly'])
        if a in names:
            raise BadInput('assembly %r is listed twice' % a)
        names.append(a)
        if a == working:
            steps.append(dict(assembly=a, version='working', module=os.path.join(project, 'src', a + '.py'),
                              depends_on=None))
            continue
        d = os.path.join(project, 'accepted', a, version_dir(e['version']))
        mod = os.path.join(d, a + '.py')
        if not os.path.isfile(mod):
            raise BadInput('accepted module not found: %s' % mod)
        man = load_json(os.path.join(d, 'manifest.json'), 'manifest of %s %s' % (a, version_dir(e['version'])))
        if not isinstance(man, dict) or not man.get('sha256'):
            raise BadInput('manifest of %s %s has no sha256' % (a, version_dir(e['version'])))
        got = sha256(mod)
        if str(man['sha256']).lower() != got:
            problems.append('%s %s: the module does not match its manifest hash' % (a, version_dir(e['version'])))
        dep = man.get('depends_on', [])
        if not isinstance(dep, list):
            raise BadInput('manifest of %s: depends_on must be a list' % a)
        steps.append(dict(assembly=a, version=version_dir(e['version']), module=mod, sha256=got,
                          depends_on=[str(x) for x in dep]))
    if working and working not in names:
        steps.append(dict(assembly=working, version='working', module=os.path.join(project, 'src', working + '.py'),
                          depends_on=None))
    if working and not os.path.isfile(steps[[s['assembly'] for s in steps].index(working)]['module']):
        raise BadInput('working module not found: src/%s.py' % working)
    for i, s in enumerate(steps):
        before = [x['assembly'] for x in steps[:i]]
        for d in s['depends_on'] or []:
            if d not in before:
                problems.append('%s depends on %s, which is not built before it' % (s['assembly'], d))
    return steps, problems


def load_module(path, name):
    spec = importlib.util.spec_from_file_location('rg_module_' + name.replace('-', '_'), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, 'build', None)):
        raise RuntimeError('%s has no build(ctx)' % os.path.basename(path))
    return mod


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--project', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--build')
    ap.add_argument('--working')
    ap.add_argument('--look')
    ap.add_argument('--out')
    a = ap.parse(argv)
    project = os.path.abspath(a.project)
    if not os.path.isdir(project):
        raise BadInput('project folder not found: %s' % project)
    build = load_json(a.build or os.path.join(project, 'data', 'build.json'), 'build list')
    if not isinstance(build, list):
        raise BadInput('the build list must be a JSON list')
    if not build and not a.working:
        raise BadInput('the build list is empty')
    vehicle = load_json(os.path.join(project, 'data', 'vehicle.json'), 'vehicle.json')
    finishes = kit.read_json(os.path.join(project, 'data', 'finishes.json'))
    parts = kit.read_json(os.path.join(project, 'data', 'parts.json'), [])
    out = os.path.abspath(a.out or os.path.join(project, 'out', ('work-%s.blend' % a.working) if a.working
                                                else 'vehicle.blend'))
    steps, problems = plan(project, build, a.working)
    log = dict(project=project, out=out, look=None, steps=[], problems=problems, warnings=[])
    if problems:
        for p in problems:
            print('STOP', p)
        log['passed'] = False
        save_json(out + '.json', log)
        return EXIT_GATE
    bpy = B.bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 1.0
    try:
        ctx = kit.Context(vehicle, finishes, a.look, parts)
    except KeyError as e:
        raise BadInput(str(e))
    log['look'] = ctx.look
    for s in steps:
        t0 = time.monotonic()
        entry = {k: v for k, v in s.items() if k != 'module'}
        entry['module'] = os.path.relpath(s['module'], project).replace(os.sep, '/')
        ctx.assembly = s['assembly']
        try:
            load_module(s['module'], s['assembly']).build(ctx)
            bpy.context.view_layer.update()
        except BaseException as e:            # a module calling sys.exit is a failed step too
            entry.update(status='failed', error='%s: %s' % (type(e).__name__, e), traceback=traceback.format_exc(),
                         seconds=round(time.monotonic() - t0, 2))
            log['steps'].append(entry)
            log['passed'] = False
            save_json(out + '.json', log)
            print('FAILED in %s: %s' % (s['assembly'], entry['error']))
            print(entry['traceback'])
            return EXIT_GATE
        ctx.assembly = None
        entry.update(status='built', objects=ctx.added.get(s['assembly'], []), seconds=round(time.monotonic() - t0, 2))
        log['steps'].append(entry)
        print('built %s %s: %d objects' % (s['assembly'], s['version'], len(entry['objects'])))
    log['warnings'] = ctx.warnings
    sc['rg_look'] = ctx.look or ''
    sc['rg_build'] = json.dumps([dict(assembly=s['assembly'], version=s['version'],
                                      sha256=s.get('sha256')) for s in steps])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    log['passed'] = os.path.isfile(out)
    save_json(out + '.json', log)
    print('ASSEMBLED', out)
    return EXIT_OK if log['passed'] else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
