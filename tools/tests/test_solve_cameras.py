import numpy as np

from conftest import box_corners, camera_at, read_json, run_tool, write_json

VIEWS = {
    'side': (1200.0, -7000.0, 900.0),
    'front-34': (-5000.0, -4200.0, 1500.0),
    'rear': (9000.0, 300.0, 1100.0),
}


def landmarks(noise_px=0.3, seed=1, bad_view=None):
    rng = np.random.default_rng(seed)
    pts = box_corners()
    names = list(pts)
    X = np.array([pts[n] for n in names])
    photos = {}
    truth = {}
    for v, C in VIEWS.items():
        cam = camera_at(C, f=1500.0 if v != 'rear' else 2600.0)
        truth[v] = cam
        uv = cam.project(X) + rng.normal(0, noise_px, (len(X), 2))
        if v == bad_view:
            uv[:3] += 60.0            # three badly marked points
        photos[v] = {'width': cam.width, 'height': cam.height,
                     'points': {n: [float(u), float(w)] for n, (u, w) in zip(names, uv)}}
    # wheel contact points from the maker's dimensions are known too
    return {'photos': photos}, truth


def test_solves_known_cameras(project):
    lm, truth = landmarks()
    write_json(project / 'data' / 'landmarks.json', lm)
    r = run_tool('solve_cameras.py', project)
    assert r.returncode == 0, r.stdout + r.stderr
    out = read_json(project / 'data' / 'cameras.json')
    assert out['passed'] is True
    for v, cam in truth.items():
        c = out['cameras'][v]
        assert np.linalg.norm(np.array(c['position_mm']) - cam.C) < 0.02 * np.linalg.norm(cam.C)
        assert abs(c['focal_px'] - cam.f) / cam.f < 0.03
        assert c['errors']['rms_px'] < 1.0
        assert c['errors']['rms_mm'] < 12.0
        assert np.allclose(c['centre_px'], [(cam.width - 1) / 2, (cam.height - 1) / 2])


def test_bad_marks_fail_the_gate(project):
    lm, _ = landmarks(bad_view='side')
    write_json(project / 'data' / 'landmarks.json', lm)
    r = run_tool('solve_cameras.py', project, '--max-rms-mm', 12)
    assert r.returncode == 1, r.stdout + r.stderr
    out = read_json(project / 'data' / 'cameras.json')
    assert out['passed'] is False
    assert out['cameras']['side']['passed'] is False
    assert out['cameras']['rear']['passed'] is True


def test_bad_input(project):
    r = run_tool('solve_cameras.py')
    assert r.returncode == 2 and 'usage' in r.stdout
    lm, _ = landmarks()
    lm['photos']['side']['points']['no_such_point'] = [10, 10]
    write_json(project / 'data' / 'landmarks.json', lm)
    r = run_tool('solve_cameras.py', project)
    assert r.returncode == 2 and 'no_such_point' in r.stderr
    (project / 'data' / 'landmarks.json').write_text('{not json', encoding='utf-8')
    assert run_tool('solve_cameras.py', project).returncode == 2
