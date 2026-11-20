import os

import numpy as np

from conftest import (DIMS, OrthoCamera, blank_picture, box_corners, camera_at, read_json, run_tool,
                      write_json)

# named points worked out from DIMS, as the solver does
HUB_Y = DIMS['track_front'] / 2 + DIMS['tyre_width_front'] / 2
NAMED = {
    'contact_fl': [0.0, -780.0, 0.0], 'contact_fr': [0.0, 780.0, 0.0],
    'contact_rl': [2500.0, -790.0, 0.0], 'contact_rr': [2500.0, 790.0, 0.0],
    'hub_fl': [0.0, -HUB_Y, 330.0], 'hub_fr': [0.0, HUB_Y, 330.0],
    'rim_top_fl': [0.0, -HUB_Y, 580.0], 'rim_front_fl': [-250.0, -HUB_Y, 330.0],
}
FRONT_EXTREME = [-900.0, 0.0, 700.0]          # only X is known to the solver
ROOF_TOP = [1200.0, 0.0, 1300.0]              # only Z is known to the solver


def known():
    p = dict(box_corners())
    p.update(NAMED)
    p['front_extreme'] = FRONT_EXTREME
    p['roof_top'] = ROOF_TOP
    return p


SIDE_POINTS = ['flb', 'flt', 'rlb', 'rlt', 'contact_fl', 'contact_rl', 'hub_fl', 'rim_top_fl', 'rim_front_fl']


def views():
    """name: (camera, points it marks, file size, crop or None)."""
    return {
        'front-34-left': (camera_at((-5000.0, -4200.0, 1500.0), f=1500.0, w=1600, h=1000),
                          ['flb', 'flt', 'frb', 'frt', 'rlb', 'rlt', 'contact_fl', 'hub_fl', 'front_extreme',
                           'roof_top'], (1800, 1100), [100, 50, 1700, 1050]),
        'front-34-right': (camera_at((-5000.0, 4300.0, 1600.0), f=1500.0, w=1600, h=1000),
                           ['flb', 'flt', 'frb', 'frt', 'rrb', 'rrt', 'contact_fr', 'hub_fr', 'front_extreme',
                            'roof_top'], (1600, 1000), None),
        'rear-34-right': (camera_at((8200.0, 4600.0, 1700.0), f=1500.0, w=1600, h=1000),
                          ['rlb', 'rlt', 'rrb', 'rrt', 'frb', 'frt', 'contact_rr', 'roof_top'], (1600, 1000), None),
        'side-left': (camera_at((1200.0, -9000.0, 800.0), f=1600.0, w=1600, h=1000), SIDE_POINTS,
                      (1600, 1000), None),
    }


def side_drawing():
    R = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    return OrthoCamera([1200.0, -20000.0, 650.0], R, 0.1, 249.5, 99.5, 500, 200)


def write_landmarks(project, noise=0.3, seed=1, drop=None, focal_side=False):
    rng = np.random.default_rng(seed)
    pts = known()
    lm = []
    for v, (cam, names, size, crop) in views().items():
        f = 'refs/photos/%s.png' % v
        blank_picture(project / f, *size)
        off = crop[:2] if crop else (0, 0)
        uv = cam.project(np.array([pts[n] for n in names])) + rng.normal(0, noise, (len(names), 2))
        e = dict(view=v, file=f, kind='photo', steer_deg=0,
                 points={n: [float(a + off[0]), float(b + off[1])] for n, (a, b) in zip(names, uv)})
        if crop:
            e['crop'] = crop
        if v == 'side-left' and focal_side:
            e.update(focal_mm=1600.0 / 1600 * 36.0, sensor_mm=36.0)
        lm.append(e)
    dcam = side_drawing()
    f = 'refs/blueprints/sheet.png'
    blank_picture(project / f, 500, 200, (255, 255, 255))
    uv = dcam.project(np.array([pts[n] for n in SIDE_POINTS])) + rng.normal(0, noise, (len(SIDE_POINTS), 2))
    lm.append(dict(view='side-drawing', file=f, kind='drawing', steer_deg=0,
                   points={n: [float(a), float(b)] for n, (a, b) in zip(SIDE_POINTS, uv)}))
    if drop:
        for e in lm:
            if e['view'] == drop:
                for k in list(e['points'])[6 - 1:]:
                    e['points'].pop(k)
    write_json(project / 'data' / 'landmarks.json', lm)


def test_solves_photos_and_drawings(project):
    write_landmarks(project)
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 0, r.stdout + r.stderr
    out = read_json(project / 'data' / 'cameras.json')
    cams = out['cameras']
    for v, (cam, _, _, crop) in views().items():
        c = cams[v]
        assert np.linalg.norm(np.array(c['position_mm']) - cam.C) < 0.02 * np.linalg.norm(cam.C), v
        assert (c['width'], c['height']) == (cam.width, cam.height)
    assert cams['front-34-left']['crop'] == [100, 50, 1700, 1050]
    assert cams['front-34-left']['grade'] == 'precise'
    # a face-on side photo with every known point in one plane: direction solves, distance does not
    assert cams['side-left']['grade'] == 'visual' and cams['side-left']['planar'] is True
    d = cams['side-drawing']
    assert d['kind'] == 'orthographic' and d['grade'] == 'precise'
    assert abs(d['scale_px_per_mm'] - 0.1) < 0.002
    assert out['precise_views'] == 4
    # partly known points solved with the cameras
    assert np.allclose(out['solved_points']['front_extreme'], FRONT_EXTREME, atol=15)
    assert np.allclose(out['solved_points']['roof_top'], ROOF_TOP, atol=15)


def test_focal_length_makes_a_flat_view_precise(project):
    write_landmarks(project, focal_side=True)
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(project / 'data' / 'cameras.json')['cameras']['side-left']['grade'] == 'precise'


def test_too_few_precise_views_fail(project):
    write_landmarks(project)
    r = run_tool('solve_cameras.py', '--project', project, '--min-precise', 5)
    assert r.returncode == 1, r.stdout + r.stderr
    assert read_json(project / 'data' / 'cameras.json')['passed'] is False


def test_triangulate(project):
    write_landmarks(project, noise=0.0)
    assert run_tool('solve_cameras.py', '--project', project).returncode == 0
    X = np.array([2000.0, -900.0, 1000.0])
    px = []
    for v in ('front-34-left', 'side-left', 'side-drawing'):
        if v == 'side-drawing':
            uv, off = side_drawing().project(X)[0], (0, 0)
        else:
            cam, _, _, crop = views()[v]
            uv, off = cam.project(X)[0], (crop[:2] if crop else (0, 0))
        px.append(dict(name='door handle', view=v, u=float(uv[0] + off[0]), v=float(uv[1] + off[1])))
    pf = write_json(project / 'data' / 'pixels.json', px)
    r = run_tool('solve_cameras.py', '--project', project, '--triangulate', pf)
    assert r.returncode == 0, r.stdout + r.stderr
    t = read_json(project / 'data' / 'pixels-triangulated.json')['points']['door handle']
    assert np.allclose(t['position_mm'], X, atol=5)
    assert all(e['px'] < 1.0 for e in t['views'].values())


def test_bad_input(project):
    assert run_tool('solve_cameras.py').returncode == 2
    write_landmarks(project, drop='rear-34-right')
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 2 and 'at least 6' in r.stderr
    lm = read_json(project / 'data' / 'landmarks.json')
    write_landmarks(project)
    lm = read_json(project / 'data' / 'landmarks.json')
    lm[0]['points']['no_such_point'] = [10, 10]
    write_json(project / 'data' / 'landmarks.json', lm)
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 2 and 'no_such_point' in r.stderr
    write_landmarks(project)
    lm = read_json(project / 'data' / 'landmarks.json')
    del lm[1]['steer_deg']
    write_json(project / 'data' / 'landmarks.json', lm)
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 2 and "missing key 'steer_deg'" in r.stderr
    v = read_json(project / 'data' / 'vehicle.json')
    del v['trim']
    write_json(project / 'data' / 'vehicle.json', v)
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 2 and "missing key 'trim'" in r.stderr
    write_json(project / 'data' / 'vehicle.json', dict(v, trim='test'))
    write_landmarks(project)
    os.remove(project / 'refs' / 'photos' / 'side-left.png')
    assert run_tool('solve_cameras.py', '--project', project).returncode == 2
