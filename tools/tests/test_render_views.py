"""render_views.py in headless Blender, checked against the plain camera model and compare.py."""
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import BOX, camera_at, read_json, run_blender, run_tool, write_json

pytestmark = pytest.mark.blender


def corners():
    b = BOX
    return np.array([[x, y, z] for x in (b['x0'], b['x1']) for y in (-b['y'], b['y']) for z in (150.0, b['z1'])])


def cameras(project, away=False):
    cams = {
        # off-centre optical centre, to prove the shift is converted correctly
        'front-34': camera_at((-5200.0, -4600.0, 1700.0), f=150.0, w=160, h=100, cx=86.0, cy=46.0),
        'side': camera_at((1200.0, -9000.0, 800.0), f=160.0, w=160, h=100),
    }
    if away:
        cams['side'] = camera_at((1200.0, -9000.0, 800.0), at=(1200.0, -20000.0, 800.0), f=160.0, w=160, h=100)
    d = {'cameras': {k: c.as_dict() for k, c in cams.items()}}
    write_json(project / 'data' / 'cameras.json', d)
    return cams


def draw_mask(cam, path):
    from scipy.spatial import ConvexHull
    uv = cam.project(corners())
    hull = uv[ConvexHull(uv).vertices]
    m = Image.new('L', (cam.width, cam.height), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in (hull + 0.5)], fill=255)
    m.save(path)
    Image.merge('RGB', [m, m, m]).save(str(path).replace('masks', 'photos'))


def test_render_views_match_the_camera_model(blender, scenes, project):
    cams = cameras(project)
    out = project / 'evidence' / 'round-01' / 'renders'
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--cameras', project / 'data' / 'cameras.json',
                    '--out', out, '--mode', 'clay', '--samples', 2)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render.json')
    assert res['mode'] == 'clay' and res['passed'] is True and res['device'] == 'CPU'
    for v, cam in cams.items():
        e = res['views'][v]
        assert e['projection_error_px'] < 0.5
        im = Image.open(out / (v + '.png'))
        assert im.size == (cam.width, cam.height) and im.mode == 'RGBA'
        draw_mask(cam, project / 'refs' / 'masks' / (v + '.png'))
    # the render's silhouette lies on the silhouette the plain camera model predicts
    r = run_tool('compare.py', '--photos', project / 'refs' / 'photos', '--masks', project / 'refs' / 'masks',
                 '--renders', out, '--out', project / 'evidence' / 'round-01', '--cameras',
                 project / 'data' / 'cameras.json', '--ref-width', 160, '--max-median-px', 1, '--max-p95-px', 1.5)
    assert r.returncode == 0, r.stdout + r.stderr


def test_render_views_zebra_and_settings_reuse(blender, scenes, project):
    cameras(project)
    out1 = project / 'evidence' / 'round-01' / 'renders'
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--cameras', project / 'data' / 'cameras.json',
                    '--out', out1, '--mode', 'zebra', '--samples', 2, '--views', 'side')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    s1 = read_json(out1 / 'render.json')
    assert s1['look']['stripes'] == 40
    out2 = project / 'evidence' / 'round-02' / 'renders'
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--cameras', project / 'data' / 'cameras.json',
                    '--out', out2, '--settings', out1 / 'render.json', '--views', 'side')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    s2 = read_json(out2 / 'render.json')
    assert (s2['mode'], s2['samples'], s2['engine']) == (s1['mode'], s1['samples'], s1['engine'])


def test_render_views_gate_fails_when_a_camera_misses_the_vehicle(blender, scenes, project):
    cameras(project, away=True)
    out = project / 'evidence' / 'round-01' / 'renders'
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--cameras', project / 'data' / 'cameras.json',
                    '--out', out, '--samples', 1)
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render.json')
    assert res['views']['side']['checks']['vehicle_in_picture'] is False
    assert res['views']['front-34']['passed'] is True


def test_render_views_bad_input(blender, scenes, project):
    cameras(project)
    r = run_blender(blender, scenes['plain'], 'render_views.py')
    assert r.returncode == 2 and 'usage' in r.stdout
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--cameras', project / 'data' / 'cameras.json',
                    '--out', project / 'x', '--finish', 'no-such-finish')
    assert r.returncode == 2, r.stdout[-2000:] + r.stderr[-2000:]
    assert not os.path.exists(project / 'x' / 'render.json')
