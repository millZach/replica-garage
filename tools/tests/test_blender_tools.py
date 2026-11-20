"""The Blender tools on tiny synthetic scenes (see scenes.py), one headless Blender run at a time."""
import hashlib
import os

import numpy as np
import pytest
from PIL import Image

from conftest import DIMS, VEHICLE, camera_at, camera_entry, landmark_entry, read_json, run_blender, write_json

pytestmark = pytest.mark.blender


def ok(r, code=0):
    assert r.returncode == code, 'exit %d, wanted %d\n%s\n%s' % (r.returncode, code, r.stdout[-3000:],
                                                                 r.stderr[-3000:])


def tool(blender, scene, name, project, *args):
    return run_blender(blender, scene, name, '--project', project, *args)


# ------------------------------------------------------------------ assemble

BODY = '''import bpy

def build(ctx):
    me = bpy.data.meshes.new('shell')
    x0, x1, y, z0, z1 = ctx.mm(-900), ctx.mm(3300), ctx.mm(900), ctx.mm(150), ctx.mm(1300)
    v = [(a, b, c) for a in (x0, x1) for b in (-y, y) for c in (z0, z1)]
    me.from_pydata(v, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    ob = bpy.data.objects.new('shell', me)
    me.materials.append(ctx.material('body'))
    ctx.add(ob, part='body shell', panel=True)
    ctx.crease(ob, [0, 1])
'''
LAMP = '''import bpy

def build(ctx):
    hit = ctx.body.hit((ctx.mm(-2000), 0.0, ctx.mm(700)), (1.0, 0.0, 0.0))
    assert hit is not None and abs(hit[0].x - ctx.mm(-900)) < 1e-6, hit
    me = bpy.data.meshes.new('lamp')
    x = hit[0].x - ctx.mm(2)
    me.from_pydata([(x, -0.1, 0.6), (x, 0.1, 0.6), (x, 0.1, 0.8), (x, -0.1, 0.8)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new('lamp', me)
    me.materials.append(ctx.material('lens'))
    ctx.add(ob, part='lamp', pivot=ctx.part('lamp')['pivot'])
'''
TRIM = '''import bpy

def build(ctx):
    me = bpy.data.meshes.new('trim')
    me.from_pydata([(0, 0, 1.4), (0.1, 0, 1.4), (0.1, 0.1, 1.4)], [], [(0, 1, 2)])
    ctx.add(bpy.data.objects.new('trim', me), part='trim')
'''


def accept(project, assembly, version, code, depends=()):
    d = project / 'accepted' / assembly / ('%02d' % version)
    os.makedirs(d, exist_ok=True)
    (d / (assembly + '.py')).write_bytes(code.encode('utf-8'))
    write_json(d / 'manifest.json', {'assembly': assembly, 'version': version, 'depends_on': list(depends),
                                     'sha256': hashlib.sha256(code.encode('utf-8')).hexdigest()})
    return d


def assembly_project(project):
    accept(project, 'body', 0, BODY)
    accept(project, 'front', 1, LAMP, depends=['body'])
    write_json(project / 'data' / 'build.json', [{'assembly': 'body', 'version': 0, 'seats': []},
                                                 {'assembly': 'front', 'version': 1,
                                                  'seats': [{'part': 'lamp', 'on': 'body shell'}]}])
    write_json(project / 'data' / 'finishes.json', {'proof_look': 'white', 'looks': {'white': {
        'studio': 'soft', 'slots': {'body': {'base_color': [0.8, 0.8, 0.8]}, 'lens': {'transmission': 1}}}}})
    write_json(project / 'data' / 'parts.json', [{'part': 'lamp', 'fixed_to': 'body shell',
                                                  'pivot': [-902.0, 0.0, 700.0], 'level': 2, 'basis': 'measured'}])


def test_assemble_builds_accepted_modules(blender, project):
    assembly_project(project)
    ok(run_blender(blender, None, 'assemble.py', '--project', project))
    out = project / 'out' / 'vehicle.blend'
    log = read_json(str(out) + '.json')
    assert [s['status'] for s in log['steps']] == ['built', 'built'] and log['look'] == 'white'
    assert log['steps'][0]['objects'] == ['shell']
    # the built scene carries the kit's registrations: seating reads them back by part name
    ok(run_blender(blender, out, 'seating.py', '--project', project, '--out', project / 'ev'))
    s = read_json(project / 'ev' / 'seating.json')['seats'][0]
    assert s['part'] == 'lamp' and s['max_abs_step_mm'] == pytest.approx(2.0, abs=0.01)
    # a builder's working module from src/, added after the listed ones
    os.makedirs(project / 'src')
    (project / 'src' / 'trim.py').write_bytes(TRIM.encode('utf-8'))
    ok(run_blender(blender, None, 'assemble.py', '--project', project, '--working', 'trim'))
    log = read_json(str(project / 'out' / 'work-trim.blend') + '.json')
    assert [s['assembly'] for s in log['steps']] == ['body', 'front', 'trim']
    assert log['steps'][2]['version'] == 'working'


def test_assemble_stops_on_mismatch_order_or_error(blender, project):
    assembly_project(project)
    mod = project / 'accepted' / 'body' / '00' / 'body.py'
    mod.write_bytes((BODY + '\n# changed after it was accepted\n').encode('utf-8'))
    ok(run_blender(blender, None, 'assemble.py', '--project', project), 1)
    assert 'does not match' in read_json(str(project / 'out' / 'vehicle.blend') + '.json')['problems'][0]
    assert not (project / 'out' / 'vehicle.blend').exists()
    accept(project, 'body', 0, BODY)
    write_json(project / 'data' / 'build.json', [{'assembly': 'front', 'version': 1, 'seats': []},
                                                 {'assembly': 'body', 'version': 0, 'seats': []}])
    ok(run_blender(blender, None, 'assemble.py', '--project', project), 1)
    accept(project, 'body', 0, BODY.replace("ctx.material('body')", "ctx.material('no such slot')"))
    write_json(project / 'data' / 'build.json', [{'assembly': 'body', 'version': 0, 'seats': []}])
    ok(run_blender(blender, None, 'assemble.py', '--project', project), 1)
    assert read_json(str(project / 'out' / 'vehicle.blend') + '.json')['steps'][0]['status'] == 'failed'


def test_assemble_bad_input(blender, project, tmp_path):
    ok(run_blender(blender, None, 'assemble.py'), 2)
    ok(run_blender(blender, None, 'assemble.py', '--project', project), 2)          # no build.json
    write_json(project / 'data' / 'build.json', [{'assembly': 'body', 'version': 7, 'seats': []}])
    ok(run_blender(blender, None, 'assemble.py', '--project', project), 2)          # no such accepted version
    write_json(project / 'data' / 'build.json', [{'assembly': 'body', 'version': 0}])
    r = run_blender(blender, None, 'assemble.py', '--project', project)
    ok(r, 2)
    assert "missing key 'seats'" in r.stderr


# ------------------------------------------------------------------ dimensions

def test_dimensions_pass(blender, scenes, project):
    out = project / 'evidence' / 'round-01'
    ok(tool(blender, scenes['car'], 'dimensions.py', project, '--out', out))
    d = read_json(out / 'dimensions.json')['dimensions']
    for k in ('length', 'width', 'height', 'wheelbase', 'track_front', 'track_rear', 'overhang_front'):
        assert abs(d[k]['error_mm']) < 1.0, (k, d[k])
    assert d['wheelbase']['measured_mm'] == pytest.approx(2500.0, abs=0.5)


def test_dimensions_gate_fails_but_not_on_estimates(blender, scenes, project):
    write_json(project / 'data' / 'vehicle.json', dict(VEHICLE, dimensions=dict(DIMS, length=4300.0, width=1700.0),
                                                       estimated=['width']))
    out = project / 'evidence' / 'round-01'
    ok(tool(blender, scenes['car'], 'dimensions.py', project, '--out', out), 1)
    d = read_json(out / 'dimensions.json')['dimensions']
    assert d['length']['error_mm'] == pytest.approx(-100.0, abs=0.5) and d['length']['passed'] is False
    assert d['width']['judged'] is False and d['width']['estimated'] is True


def test_dimensions_bad_input(blender, scenes, project):
    ok(tool(blender, scenes['car'], 'dimensions.py', project, '--out', project, '--vehicle', project / 'no.json'), 2)
    ok(tool(blender, scenes['car'], 'dimensions.py', project, '--out', project, '--wheels', 'a,b,c'), 2)


# ------------------------------------------------------------------ closeups

CLOSE = ['--size-mm', 1500, '--resolution', 24, '--samples', 1, '--samples-surface', 600]


def test_closeups_cover_both_sides(blender, scenes, project, tmp_path):
    out = tmp_path / 'close'
    ok(tool(blender, scenes['plain'], 'closeups.py', project, '--out', out, *CLOSE))
    res = read_json(out / 'closeups.json')
    assert res['mode'] == 'lit'
    names = [v['name'] for v in res['views']]
    left = [n for n in names if n.startswith('left-')]
    right = [n for n in names if n.startswith('right-')]
    assert left and sorted(n[5:] for n in left) == sorted(n[6:] for n in right)
    for r in ('left', 'right', 'front', 'rear', 'roof'):
        assert res['coverage'][r]['fraction'] >= 0.95, (r, res['coverage'][r])
    for v in res['views']:
        assert os.path.isfile(v['file']) and Image.open(v['file']).size == (24, 24)
    side = [v for v in res['views'] if v['region'] == 'right'][0]
    assert side['direction'] == [0.0, -1.0, 0.0] and side['camera_mm'][1] > 900


def test_closeups_gate_fails_when_a_side_is_left_out(blender, scenes, project, tmp_path):
    out = tmp_path / 'close'
    ok(tool(blender, scenes['plain'], 'closeups.py', project, '--out', out, *CLOSE, '--skip-regions', 'right',
            '--no-render'), 1)
    res = read_json(out / 'closeups.json')
    assert res['coverage']['right']['fraction'] == 0.0 and res['coverage']['left']['passed'] is True


def test_closeups_hide_and_bad_input(blender, scenes, project, tmp_path):
    ok(tool(blender, scenes['plain'], 'closeups.py', project, '--out', tmp_path, '--regions', 'left,underneath'), 2)
    # hiding the only part leaves nothing to look at
    ok(tool(blender, scenes['plain'], 'closeups.py', project, '--out', tmp_path, '--hide', 'body shell'), 2)
    ok(tool(blender, scenes['plain'], 'closeups.py', project, '--out', tmp_path, '--hide', 'no such part'), 2)


# ------------------------------------------------------------------ fairness

def test_fairness_pass_with_marked_crease(blender, scenes, project, tmp_path):
    ok(tool(blender, scenes['fair'], 'fairness.py', project, '--out', tmp_path))
    p = read_json(tmp_path / 'fairness.json')['panels']
    assert p['panel_smooth']['p99_deg'] < 1.0 and p['panel_smooth']['max_deg'] < 1.0
    assert p['panel_creased']['max_deg'] < 1.0 and p['panel_creased']['crease_edges'] == 40


def test_fairness_gate_fails_on_unmarked_fold(blender, scenes, project, tmp_path):
    ok(tool(blender, scenes['fair_bad'], 'fairness.py', project, '--out', tmp_path), 1)
    p = read_json(tmp_path / 'fairness.json')['panels']
    assert set(p) == {'panel_smooth', 'panel_creased', 'panel_unmarked'}
    assert p['panel_unmarked']['max_deg'] == pytest.approx(30.0, abs=0.5) and p['panel_unmarked']['passed'] is False
    assert p['panel_creased']['passed'] is True


def test_fairness_bad_input(blender, scenes, project, tmp_path):
    r = tool(blender, scenes['bare'], 'fairness.py', project, '--out', tmp_path)     # nothing registered
    ok(r, 2)
    assert 'no panels' in r.stderr


# ------------------------------------------------------------------ rays

def top_camera(project):
    R = np.array([[1.0, 0, 0], [0, -1.0, 0], [0, 0, -1.0]])
    from conftest import Camera
    c = camera_entry(Camera([0.0, 0.0, 3000.0], R, 200.0, 99.5, 49.5, 200, 100))
    write_json(project / 'data' / 'cameras.json', {'cameras': {'top': c}})
    write_json(project / 'data' / 'landmarks.json', [landmark_entry('top', 'refs/photos/top.png',
                                                                   crop=[10, 20, 210, 120])])


def test_rays_pixels_list_every_surface(blender, scenes, project, tmp_path):
    top_camera(project)
    pf = write_json(tmp_path / 'px.json', [{'name': 'single', 'view': 'top', 'u': 110, 'v': 70},
                                           {'name': 'join', 'view': 'top', 'u': 160, 'v': 70}])
    ok(tool(blender, scenes['rays'], 'rays.py', project, '--pixels', pf, '--out', tmp_path))
    r = read_json(tmp_path / 'rays.json')
    one, two = r['pixels']
    assert [h['object'] for h in one['hits']] == ['skin_outer', 'floor']
    assert one['hits'][0]['material'] == 'body' and one['hits'][0]['faces_camera'] is True
    assert one['hits'][0]['distance_mm'] == pytest.approx(3000.0, abs=1.0)
    assert [h['object'] for h in two['hits']] == ['skin_outer', 'skin_inner', 'floor']
    assert r['double_skins'] is None


def test_rays_grid_finds_double_skin(blender, scenes, project, tmp_path):
    top_camera(project)
    ok(tool(blender, scenes['rays'], 'rays.py', project, '--grid', 16, '--out', tmp_path), 1)
    r = read_json(tmp_path / 'rays.json')
    assert r['double_skins'] > 0
    pl = r['places'][0]
    assert sorted(pl['panels']) == ['skin_inner', 'skin_outer'] and pl['gap_mm'] == pytest.approx(3.0, abs=0.1)
    assert len(r['views']['top']['rays']) == 16 * 16


def test_rays_grid_single_skin_passes(blender, scenes, project, tmp_path):
    c = camera_entry(camera_at((-5200.0, -4600.0, 1700.0), f=150.0, w=160, h=100))
    write_json(project / 'data' / 'cameras.json', {'cameras': {'front-34': c}})
    ok(tool(blender, scenes['plain'], 'rays.py', project, '--grid', 12, '--out', tmp_path))
    assert read_json(tmp_path / 'rays.json')['double_skins'] == 0


def test_rays_bad_input(blender, scenes, project, tmp_path):
    top_camera(project)
    pf = write_json(tmp_path / 'px.json', [{'name': 'off', 'view': 'top', 'u': 900, 'v': 70}])
    ok(tool(blender, scenes['rays'], 'rays.py', project, '--pixels', pf, '--out', tmp_path), 2)
    pf = write_json(tmp_path / 'px.json', [{'name': 'x', 'view': 'nope', 'u': 5, 'v': 5}])
    ok(tool(blender, scenes['rays'], 'rays.py', project, '--pixels', pf, '--out', tmp_path), 2)


# ------------------------------------------------------------------ seating

def seats(project, *pairs):
    write_json(project / 'data' / 'build.json', [{'assembly': 'front', 'version': 0,
                                                  'seats': [{'part': p, 'on': o} for p, o in pairs]}])


def test_seating_pass(blender, scenes, project, tmp_path):
    seats(project, ('lamp_ok', 'bumper'))
    ok(tool(blender, scenes['seat'], 'seating.py', project, '--out', tmp_path))
    s = read_json(tmp_path / 'seating.json')['seats'][0]
    assert len(s['points']) == 72
    assert s['min_step_mm'] == pytest.approx(2.0, abs=0.05) and s['max_step_mm'] == pytest.approx(2.0, abs=0.05)


def test_seating_gate_fails(blender, scenes, project, tmp_path):
    seats(project, ('lamp_ok', 'bumper'), ('lamp_proud', 'bumper'), ('mirror', 'bumper'))
    ok(tool(blender, scenes['seat'], 'seating.py', project, '--out', tmp_path), 1)
    s = {x['part']: x for x in read_json(tmp_path / 'seating.json')['seats']}
    assert s['lamp_proud']['max_abs_step_mm'] == pytest.approx(6.0, abs=0.05) and s['lamp_ok']['passed'] is True
    assert s['mirror']['passed'] is False and 'not in the scene' in s['mirror']['note']
    # the builder's form, one part on its own trial assembly
    ok(tool(blender, scenes['seat'], 'seating.py', project, '--out', tmp_path, '--part', 'lamp_proud',
            '--on', 'bumper'), 1)


def test_seating_bad_input(blender, scenes, project, tmp_path):
    ok(tool(blender, scenes['seat'], 'seating.py', project, '--out', tmp_path, '--part', 'no_part', '--on',
            'bumper'), 2)


# ------------------------------------------------------------------ separation

PARTS = [{'part': 'door', 'fixed_to': 'wing', 'pivot': [1000.0, 0.0, 250.0], 'level': 2, 'basis': 'measured'},
         {'part': 'wing', 'fixed_to': 'body', 'pivot': [0.0, 0.0, 0.0], 'level': 2, 'basis': 'measured'},
         {'part': 'bonnet', 'fixed_to': 'wing', 'pivot': [-500.0, 250.0, 250.0], 'level': 3,
          'basis': 'reconstructed'},
         {'part': 'boot lid', 'fixed_to': 'wing', 'pivot': [3000.0, 250.0, 500.0], 'level': 3,
          'basis': 'reconstructed'},
         {'part': 'gone', 'fixed_to': 'wing', 'pivot': [0, 0, 0], 'level': 3, 'basis': 'reconstructed'}]


def test_separation_pass_and_exploded_view(blender, scenes, project, tmp_path):
    write_json(project / 'data' / 'parts.json', PARTS)
    ok(tool(blender, scenes['sep'], 'separation.py', project, '--level', 2, '--out', tmp_path,
            '--resolution', '32x20', '--samples', 1))
    r = read_json(tmp_path / 'separation.json')
    assert [p['part'] for p in r['parts']] == ['door', 'wing']
    assert all(p['own_object'] and p['pivot_ok'] for p in r['parts'])
    assert r['overlaps'][0]['depth_mm'] <= 0.5
    assert Image.open(tmp_path / 'exploded.png').size == (32, 20)


def test_separation_gate_fails(blender, scenes, project, tmp_path):
    write_json(project / 'data' / 'parts.json', PARTS)
    ok(tool(blender, scenes['sep'], 'separation.py', project, '--level', 3, '--out', tmp_path, '--no-render'), 1)
    r = read_json(tmp_path / 'separation.json')
    pair = [o for o in r['overlaps'] if {o['a'], o['b']} == {'bonnet', 'wing'}][0]
    assert pair['depth_mm'] == pytest.approx(5.0, abs=0.2) and pair['passed'] is False
    parts = {p['part']: p for p in r['parts']}
    assert parts['boot lid']['pivot_ok'] is False and parts['gone']['own_object'] is False
    assert parts['door']['pivot_ok'] is True


def test_separation_bad_input(blender, scenes, project, tmp_path):
    write_json(project / 'data' / 'parts.json', PARTS)
    ok(tool(blender, scenes['sep'], 'separation.py', project, '--level', 4, '--out', tmp_path), 2)
    write_json(project / 'data' / 'parts.json', [])
    ok(tool(blender, scenes['sep'], 'separation.py', project, '--level', 2, '--out', tmp_path), 2)
