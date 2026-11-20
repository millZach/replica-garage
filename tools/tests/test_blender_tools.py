"""The Blender tools on tiny synthetic scenes (see scenes.py), one headless Blender run at a time."""
import hashlib
import os

import pytest
from PIL import Image

from conftest import DIMS, read_json, run_blender, write_json

pytestmark = pytest.mark.blender


def ok(r, code=0):
    assert r.returncode == code, 'exit %d, wanted %d\n%s\n%s' % (r.returncode, code, r.stdout[-3000:],
                                                                 r.stderr[-3000:])


# ------------------------------------------------------------------ dimensions

def test_dimensions_pass(blender, scenes, project):
    out = project / 'evidence' / 'round-01'
    ok(run_blender(blender, scenes['car'], 'dimensions.py', '--vehicle', project / 'data' / 'vehicle.json',
                   '--out', out))
    d = read_json(out / 'dimensions.json')['dimensions']
    for k in ('length', 'width', 'height', 'wheelbase', 'track_front', 'track_rear'):
        assert abs(d[k]['error_mm']) < 1.0, (k, d[k])
    assert d['wheelbase']['measured_mm'] == pytest.approx(2500.0, abs=0.5)


def test_dimensions_gate_fails(blender, scenes, project):
    wrong = dict(DIMS, length=4300.0)
    write_json(project / 'data' / 'vehicle.json', {'dimensions': wrong})
    out = project / 'evidence' / 'round-01'
    ok(run_blender(blender, scenes['car'], 'dimensions.py', '--vehicle', project / 'data' / 'vehicle.json',
                   '--out', out), 1)
    d = read_json(out / 'dimensions.json')['dimensions']
    assert d['length']['error_mm'] == pytest.approx(-100.0, abs=0.5) and d['length']['passed'] is False
    assert d['width']['passed'] is True


def test_dimensions_bad_input(blender, scenes, project):
    ok(run_blender(blender, scenes['car'], 'dimensions.py', '--vehicle', project / 'nope.json', '--out', project), 2)
    ok(run_blender(blender, scenes['car'], 'dimensions.py', '--vehicle', project / 'data' / 'vehicle.json',
                   '--out', project, '--wheels', 'wheel_fl,wheel_fr,wheel_rl'), 2)


# ------------------------------------------------------------------ closeups

CLOSE = ['--size-mm', 1500, '--resolution', 24, '--samples', 1, '--samples-surface', 600]


def test_closeups_cover_both_sides(blender, scenes, tmp_path):
    out = tmp_path / 'close'
    ok(run_blender(blender, scenes['plain'], 'closeups.py', '--out', out, *CLOSE))
    res = read_json(out / 'closeups.json')
    names = [v['name'] for v in res['views']]
    left = [n for n in names if n.startswith('left-')]
    right = [n for n in names if n.startswith('right-')]
    assert left and len(left) == len(right)
    assert sorted(n.replace('left-', '') for n in left) == sorted(n.replace('right-', '') for n in right)
    for r in ('left', 'right', 'front', 'rear', 'roof'):
        assert res['coverage'][r]['fraction'] >= 0.95, (r, res['coverage'][r])
    for v in res['views']:
        assert os.path.isfile(v['file']) and Image.open(v['file']).size == (24, 24)
        assert len(v['centre_mm']) == 3 and len(v['direction']) == 3
    side = [v for v in res['views'] if v['region'] == 'right'][0]
    assert side['direction'] == [0.0, -1.0, 0.0] and side['camera_mm'][1] > 900


def test_closeups_gate_fails_when_a_side_is_left_out(blender, scenes, tmp_path):
    out = tmp_path / 'close'
    ok(run_blender(blender, scenes['plain'], 'closeups.py', '--out', out, *CLOSE, '--skip-regions', 'right',
                   '--no-render'), 1)
    res = read_json(out / 'closeups.json')
    assert res['coverage']['right']['fraction'] == 0.0 and res['coverage']['right']['passed'] is False
    assert res['coverage']['left']['passed'] is True


def test_closeups_bad_input(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['plain'], 'closeups.py', '--out', tmp_path, '--regions', 'left,underneath'), 2)
    ok(run_blender(blender, scenes['plain'], 'closeups.py'), 2)


# ------------------------------------------------------------------ fairness

def test_fairness_pass_with_crease_named(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['fair'], 'fairness.py', '--panels', 'panel_*', '--creases', 'fold',
                   '--out', tmp_path))
    p = read_json(tmp_path / 'fairness.json')['panels']
    assert p['panel_smooth']['p99_deg'] < 1.0 and p['panel_smooth']['max_deg'] < 1.0
    assert p['panel_creased']['max_deg'] < 1.0 and p['panel_creased']['crease_edges'] == 40


def test_fairness_gate_fails_on_unnamed_fold(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['fair'], 'fairness.py', '--panels', 'panel_creased', '--out', tmp_path), 1)
    p = read_json(tmp_path / 'fairness.json')['panels']['panel_creased']
    assert p['max_deg'] == pytest.approx(30.0, abs=0.5) and p['passed'] is False


def test_fairness_bad_input(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['fair'], 'fairness.py', '--panels', 'no_such_panel', '--out', tmp_path), 2)
    ok(run_blender(blender, scenes['fair'], 'fairness.py', '--panels', 'panel_smooth', '--creases', 'no_such',
                   '--out', tmp_path), 2)


# ------------------------------------------------------------------ rays

def test_rays_single_skin(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['rays'], 'rays.py', '--camera', 'cam_top', '--pixels', '100,50;20,50',
                   '--painted', 'Paint*', '--out', tmp_path))
    r = read_json(tmp_path / 'rays.json')
    hits = r['pixels'][0]['hits']
    assert [h['object'] for h in hits] == ['skin_outer', 'floor']
    assert hits[0]['material'] == 'Paint skin' and hits[0]['faces_camera'] is True
    assert hits[0]['distance_mm'] == pytest.approx(3000.0, abs=1.0)
    assert r['double_skins'] == 0


def test_rays_double_skin_fails(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['rays'], 'rays.py', '--camera', 'cam_top', '--pixels', '150,50',
                   '--painted', 'Paint*', '--out', tmp_path), 1)
    r = read_json(tmp_path / 'rays.json')
    px = r['pixels'][0]
    assert px['double_skin'] is True and r['double_skins'] == 1
    d = [h['distance_mm'] for h in px['hits'][:2]]
    assert d[1] - d[0] == pytest.approx(3.0, abs=0.1)


def test_rays_bad_input(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['rays'], 'rays.py', '--camera', 'cam_top', '--pixels', '500,50',
                   '--out', tmp_path), 2)
    ok(run_blender(blender, scenes['rays'], 'rays.py', '--camera', 'no_cam', '--pixels', '5,5', '--out', tmp_path), 2)


# ------------------------------------------------------------------ seating

def test_seating_pass(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['seat'], 'seating.py', '--part', 'lamp_ok', '--panel', 'panel', '--out', tmp_path))
    r = read_json(tmp_path / 'seating.json')
    assert len(r['points']) == 72
    assert r['min_step_mm'] == pytest.approx(2.0, abs=0.05) and r['max_step_mm'] == pytest.approx(2.0, abs=0.05)


def test_seating_gate_fails(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['seat'], 'seating.py', '--part', 'lamp_proud', '--panel', 'panel',
                   '--out', tmp_path), 1)
    assert read_json(tmp_path / 'seating.json')['max_abs_step_mm'] == pytest.approx(6.0, abs=0.05)


def test_seating_bad_input(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['seat'], 'seating.py', '--part', 'no_part', '--panel', 'panel',
                   '--out', tmp_path), 2)


# ------------------------------------------------------------------ separation

def test_separation_pass_and_exploded_view(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['sep'], 'separation.py', '--level', 2, '--parts', 'door,wing', '--out', tmp_path,
                   '--resolution', '32x20', '--samples', 1))
    r = read_json(tmp_path / 'separation.json')
    assert all(p['own_object'] and p['pivot_ok'] for p in r['parts'])
    assert r['overlaps'][0]['depth_mm'] <= 0.5
    assert Image.open(tmp_path / 'exploded.png').size == (32, 20)


def test_separation_gate_fails(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['sep'], 'separation.py', '--level', 3, '--parts', 'bonnet,wing,far_pivot,gone',
                   '--out', tmp_path, '--no-render'), 1)
    r = read_json(tmp_path / 'separation.json')
    pair = [o for o in r['overlaps'] if {o['a'], o['b']} == {'bonnet', 'wing'}][0]
    assert pair['depth_mm'] == pytest.approx(5.0, abs=0.2) and pair['passed'] is False
    parts = {p['name']: p for p in r['parts']}
    assert parts['far_pivot']['pivot_ok'] is False and parts['gone']['own_object'] is False


def test_separation_bad_input(blender, scenes, tmp_path):
    ok(run_blender(blender, scenes['sep'], 'separation.py', '--level', 4, '--parts', 'door', '--out', tmp_path), 2)


# ------------------------------------------------------------------ merge

def patch(project, name, code, requires=(), touches=(), extra=None):
    f = project / 'accepted' / name
    os.makedirs(f, exist_ok=True)
    (f / 'apply.py').write_bytes(code.encode('utf-8'))
    files = {'apply.py': code}
    for k, v in (extra or {}).items():
        (f / k).write_bytes(v.encode('utf-8'))
        files[k] = v
    write_json(f / 'manifest.json', {'area': name.rsplit('-', 1)[0], 'number': int(name.rsplit('-', 1)[1]),
                                     'sha256': {k: hashlib.sha256(v.encode('utf-8')).hexdigest()
                                                for k, v in files.items()},
                                     'requires': list(requires), 'touches': list(touches)})
    return f


RAISE = "import bpy\nbpy.data.objects['body'].location.z += 0.010\n"
WIDEN = ("import bpy, json\n"
         "def apply(folder):\n"
         "    s = json.load(open('scale.json'))['y']\n"
         "    bpy.data.objects['body'].scale.y = s\n")


def test_merge_applies_in_order(blender, scenes, project):
    a = patch(project, 'body-01', RAISE, touches=['body'])
    b = patch(project, 'body-02', WIDEN, requires=['body-01'], touches=['body'], extra={'scale.json': '{"y": 1.1}'})
    out = project / 'merged.blend'
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', out, a, b))
    log = read_json(str(out) + '.json')
    assert [s['status'] for s in log['steps']] == ['applied', 'applied']
    write_json(project / 'data' / 'vehicle.json', {'dimensions': {'height': 1310.0, 'width': 1980.0}})
    ok(run_blender(blender, out, 'dimensions.py', '--vehicle', project / 'data' / 'vehicle.json',
                   '--out', project / 'evidence' / 'round-01', '--only', 'height,width'))
    d = read_json(project / 'evidence' / 'round-01' / 'dimensions.json')['dimensions']
    assert d['height']['measured_mm'] == pytest.approx(1310.0, abs=0.5)
    assert d['width']['measured_mm'] == pytest.approx(1980.0, abs=0.5)


def test_merge_stops_on_changed_or_failing_patch(blender, scenes, project):
    a = patch(project, 'body-01', RAISE)
    (a / 'apply.py').write_text(RAISE + "bpy.data.objects['body'].scale.x = 2\n", encoding='utf-8')
    out = project / 'merged.blend'
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', out, a), 1)
    assert not out.exists() and 'does not match' in read_json(str(out) + '.json')['problems'][0]
    b = patch(project, 'trim-01', "raise RuntimeError('broken patch')\n")
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', out, b), 1)
    assert not out.exists() and read_json(str(out) + '.json')['steps'][0]['status'] == 'failed'
    c = patch(project, 'body-03', RAISE, touches=['body'])
    d = patch(project, 'roof-01', RAISE, touches=['body'])
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', out, c, d), 1)


def test_merge_bad_input(blender, scenes, project, tmp_path):
    live = tmp_path / 'notes' / 'body-01'
    os.makedirs(live)
    (live / 'apply.py').write_text(RAISE, encoding='utf-8')
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', project / 'm.blend', live), 2)
    ok(run_blender(blender, scenes['plain'], 'merge.py', '--out', scenes['plain'],
                   patch(project, 'body-01', RAISE)), 2)
