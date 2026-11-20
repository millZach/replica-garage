"""render_views.py in headless Blender, checked against the plain camera model and compare.py."""
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from conftest import (BOX, OrthoCamera, camera_at, camera_entry, landmark_entry, read_json, run_blender,
                      run_tool, write_json)

pytestmark = pytest.mark.blender

FINISHES = {'proof_look': 'white', 'looks': {
    'white': {'studio': 'gloss', 'slots': {'body': {'base_color': [0.8, 0.8, 0.79], 'roughness': 0.3, 'coat': 1},
                                           'tyre': {'base_color': [0.02, 0.02, 0.02], 'roughness': 0.8}}},
    'black': {'studio': 'dark-paint', 'slots': {'body': {'base_color': [0.01, 0.01, 0.01], 'roughness': 0.3}}}}}


def corners():
    b = BOX
    return np.array([[x, y, z] for x in (b['x0'], b['x1']) for y in (-b['y'], b['y']) for z in (150.0, b['z1'])])


def cameras(project, away=False, steer=0.0):
    cams = {
        # off-centre optical centre, to prove the shift is converted correctly
        'front-34': camera_at((-5200.0, -4600.0, 1700.0), f=150.0, w=160, h=100, cx=86.0, cy=46.0),
        'side': camera_at((1200.0, -9000.0, 800.0), f=160.0, w=160, h=100),
        # a drawing: orthographic side elevation, 0.03 px per mm
        'elevation': OrthoCamera([1200.0, -20000.0, 650.0], np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]]),
                                 0.03, 79.5, 29.5, 160, 60),
    }
    if away:
        cams['side'] = camera_at((1200.0, -9000.0, 800.0), at=(1200.0, -20000.0, 800.0), f=160.0, w=160, h=100)
    write_json(project / 'data' / 'cameras.json', {'cameras': {k: camera_entry(c, steer=steer)
                                                               for k, c in cams.items()}})
    write_json(project / 'data' / 'landmarks.json',
               [landmark_entry(k, 'refs/photos/%s.png' % k, 'drawing' if k == 'elevation' else 'photo')
                for k in cams])
    return cams


def draw_mask(cam, project, v):
    from scipy.spatial import ConvexHull
    uv = cam.project(corners())
    hull = uv[ConvexHull(uv).vertices]
    m = Image.new('L', (cam.width, cam.height), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in (hull + 0.5)], fill=255)
    m.save(project / 'refs' / 'masks' / (v + '.png'))
    Image.merge('RGB', [m, m, m]).save(project / 'refs' / 'photos' / (v + '.png'))


def render(blender, scene, project, out, *args):
    return run_blender(blender, scene, 'render_views.py', '--project', project, '--out', out, *args)


def test_render_views_match_the_camera_model(blender, scenes, project):
    cams = cameras(project)
    out = project / 'evidence' / 'round-01' / 'clay'
    r = render(blender, scenes['plain'], project, out, '--mode', 'clay', '--samples', 2)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render_views.json')
    assert res['mode'] == 'clay' and res['passed'] is True and res['settings']['device'] == 'CPU'
    for v, cam in cams.items():
        e = res['views'][v]
        assert e['projection_error_px'] < 0.5, (v, e)
        im = Image.open(out / (v + '.png'))
        assert im.size == (cam.width, cam.height) and im.mode == 'RGBA'
        draw_mask(cam, project, v)
    assert res['views']['elevation']['kind'] == 'orthographic'
    # the first evidence render wrote the settings every later round uses
    assert read_json(project / 'data' / 'render.json')['samples'] == 2
    # the render's silhouette lies on the silhouette the plain camera model predicts
    r = run_tool('compare.py', '--project', project, '--renders', out, '--out', project / 'evidence' / 'round-01',
                 '--ref-width', 160, '--max-median-px', 1, '--max-p95-px', 1.5)
    assert r.returncode == 0, r.stdout + r.stderr


def test_render_views_lit_trial_and_settings_reuse(blender, scenes, project):
    cameras(project)
    write_json(project / 'data' / 'finishes.json', FINISHES)
    write_json(project / 'data' / 'render.json', {'samples': 3, 'device': 'CPU'})
    out = project / 'evidence' / 'round-01' / 'lit'
    r = render(blender, scenes['plain'], project, out, '--mode', 'lit', '--samples', 9, '--view', 'side')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render_views.json')
    assert res['settings']['samples'] == 3 and res['ignored_arguments'] == {'samples': 9}
    assert res['look']['look'] == 'white' and res['look']['studio'] == 'gloss'
    trial = project / 'out' / 'trial'
    r = render(blender, scenes['plain'], project, trial, '--mode', 'zebra', '--trial', '--view', 'side')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    t = read_json(trial / 'render_views.json')
    assert t['look']['stripes'] == 40 and t['settings']['samples'] == 16 and t['settings_file'] is None
    assert Image.open(trial / 'side.png').size == (80, 50)
    assert read_json(project / 'data' / 'render.json') == {'samples': 3, 'device': 'CPU'}


def test_render_views_steering(blender, scenes, project):
    front = camera_at((-6000.0, 0.0, 75.0), at=(0.0, 0.0, 75.0), f=400.0, w=160, h=100)   # under the body
    for steer, name in ((0.0, 'straight'), (30.0, 'steered')):
        e = camera_entry(front, steer=steer)
        write_json(project / 'data' / 'cameras.json', {'cameras': {'front': e}})
        r = render(blender, scenes['car'], project, project / name, '--mode', 'clay', '--samples', 1)
        assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    a = np.asarray(Image.open(project / 'straight' / 'front.png'))[:, :, 3] > 127
    b = np.asarray(Image.open(project / 'steered' / 'front.png'))[:, :, 3] > 127
    assert (a ^ b).sum() > 20                      # the turned front wheels change the silhouette


def test_render_views_gate_fails_when_a_camera_misses_the_vehicle(blender, scenes, project):
    cameras(project, away=True)
    out = project / 'evidence' / 'round-01' / 'clay'
    r = render(blender, scenes['plain'], project, out, '--mode', 'clay', '--samples', 1)
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render_views.json')
    assert res['views']['side']['checks']['vehicle_in_picture'] is False
    assert res['views']['front-34']['passed'] is True


def test_render_views_bad_input(blender, scenes, project):
    cameras(project)
    r = run_blender(blender, scenes['plain'], 'render_views.py')
    assert r.returncode == 2 and 'usage' in r.stdout
    write_json(project / 'data' / 'finishes.json', FINISHES)
    r = render(blender, scenes['plain'], project, project / 'x', '--mode', 'lit', '--look', 'no-such-look')
    assert r.returncode == 2, r.stdout[-2000:] + r.stderr[-2000:]
    assert not os.path.exists(project / 'x' / 'render_views.json')
