"""orbit.py, the presentation styles and the device fallback, on tiny scenes."""
import os

import numpy as np
import pytest
from PIL import Image

from conftest import camera_at, camera_entry, read_json, run_blender, write_json

pytestmark = pytest.mark.blender
SMALL = ['--resolution', '48x32', '--samples', 1, '--samples-surface', 400]


def orbit(blender, scene, project, out, *args, env=None):
    return run_blender(blender, scene, 'orbit.py', '--project', project, '--out', out, *args, env=env)


def test_orbit_ten_views_framed_and_both_sides_covered(blender, scenes, project, tmp_path):
    out = project / 'evidence' / 'round-01' / 'orbit'
    r = orbit(blender, scenes['plain'], project, out, *SMALL)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'orbit.json')
    names = [v['name'] for v in res['views']]
    assert names == ['front', 'front-left', 'left', 'rear-left', 'rear', 'rear-right', 'right', 'front-right',
                     'above-front-left', 'above-rear-right']
    for v in res['views']:
        assert os.path.isfile(v['file']) and Image.open(v['file']).size == (48, 32)
        assert v['vehicle_inside'] is True and 0.5 <= v['fill'] <= 0.9, v
    ring = [v for v in res['views'] if not v['name'].startswith('above')]
    assert all(abs(v['camera_mm'][2] - 900.0) < 1e-6 for v in ring)            # hip height
    assert res['coverage']['left']['fraction'] >= 0.95 and res['coverage']['right']['fraction'] >= 0.95
    assert res['style'] == 'showroom' and res['beauty'] is False
    assert read_json(project / 'data' / 'render.json')['samples'] == 1           # evidence settings written


def test_orbit_fails_when_the_frame_crops_the_vehicle(blender, scenes, project, tmp_path):
    r = orbit(blender, scenes['plain'], project, tmp_path / 'orbit', *SMALL, '--fill', 1.2, '--views', 'left')
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-3000:]
    assert read_json(tmp_path / 'orbit' / 'orbit.json')['views'][0]['vehicle_inside'] is False


@pytest.mark.parametrize('style', ['showroom', 'studio', 'daylight'])
def test_each_style_builds_and_renders(blender, scenes, project, tmp_path, style):
    sky = project / 'refs' / 'sky' / 'sky.png'
    os.makedirs(sky.parent, exist_ok=True)
    g = np.linspace(255, 120, 32).astype(np.uint8)[:, None].repeat(64, 1)       # a synthetic sky: a gradient
    Image.fromarray(np.stack([g // 2 + 60, g // 2 + 90, g], 2)).save(sky)
    write_json(project / 'data' / 'finishes.json', {'proof_look': 'white', 'style': style, 'sky': 'refs/sky/sky.png',
                                                    'looks': {'white': {'studio': 'soft', 'slots': {
                                                        'body': {'base_color': [0.8, 0.8, 0.8]}}}}})
    r = orbit(blender, scenes['plain'], project, tmp_path / 'orbit', *SMALL, '--views', 'front-left', '--beauty')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(tmp_path / 'orbit' / 'orbit.json')
    assert res['style'] == style and res['look']['rig'].startswith(style) and res['beauty'] is True
    px = np.asarray(Image.open(tmp_path / 'orbit' / 'front-left.png').convert('RGB')).astype(float)
    assert px.std() > 1.0                                                         # a picture, not a blank
    assert not (project / 'data' / 'render.json').exists()                       # beauty never writes settings


def test_closeups_take_a_style(blender, scenes, project, tmp_path):
    r = run_blender(blender, scenes['plain'], 'closeups.py', '--project', project, '--out', tmp_path / 'close',
                    '--size-mm', 1500, '--resolution', 16, '--samples', 1, '--samples-surface', 400,
                    '--style', 'studio')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert read_json(tmp_path / 'close' / 'closeups.json')['render']['look']['style'] == 'studio'


def test_orbit_bad_input(blender, scenes, project, tmp_path):
    r = orbit(blender, scenes['plain'], project, tmp_path, '--style', 'beach')
    assert r.returncode == 2 and 'beach' in r.stderr
    r = orbit(blender, scenes['plain'], project, tmp_path, '--style', 'daylight')
    assert r.returncode == 2 and 'sky' in r.stderr


PROBE = """
import bpy
pr = bpy.context.preferences.addons['cycles'].preferences
for t in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
    try:
        pr.compute_device_type = t
        pr.get_devices()
        n = sum(1 for d in pr.devices if d.type == t)
    except (TypeError, ValueError):
        n = 0
    print('GPUTYPE', t, n)
"""


def test_device_fallback_to_the_processor(blender, scenes, project, tmp_path):
    """Asked for a graphics card that is not there, a render tool says so and renders on the processor."""
    import subprocess
    from conftest import ENV
    probe = subprocess.run([blender, '-b', '--factory-startup', '--python-expr', PROBE], capture_output=True,
                           text=True, env=ENV, timeout=300, encoding='utf-8', errors='replace').stdout
    absent = [ln.split()[1] for ln in probe.splitlines() if ln.startswith('GPUTYPE') and ln.split()[2] == '0']
    if not absent:
        pytest.skip('every kind of graphics card is present here; nothing to fall back from')
    write_json(project / 'data' / 'cameras.json', {'cameras': {
        'side': camera_entry(camera_at((1200.0, -9000.0, 800.0), f=160.0, w=32, h=20))}})
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--project', project, '--out', tmp_path / 'r',
                    '--mode', 'clay', '--samples', 1, '--device', 'GPU', '--gpu-type', absent[0])
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert 'DEVICE FALLBACK' in r.stdout and 'DEVICE CPU' in r.stdout
    s = read_json(tmp_path / 'r' / 'render_views.json')['settings']
    assert s['device'] == 'CPU' and 'processor' in s['fallback']
