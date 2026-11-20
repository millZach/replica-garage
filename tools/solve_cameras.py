"""Solve one pinhole camera per reference photo from points whose place on the vehicle is known.

usage: python tools/solve_cameras.py <project> [--max-rms-mm 12] [--views a,b] [--free-centre]
                                     [--vehicle FILE] [--landmarks FILE] [--out FILE]

Reads <project>/data/vehicle.json and <project>/data/landmarks.json, writes <project>/data/cameras.json.
Exit 0 when every view is within --max-rms-mm at its known points, 1 when any view is worse, 2 on bad input.

vehicle.json (millimetres, vehicle coordinates):
  {"variant": "...", "dimensions": {"length": .., "width": .., "height": .., "wheelbase": .., "track_front": ..,
   "track_rear": .., "tyre_diameter_front": .., "tyre_diameter_rear": ..}, "points": {"name": [x, y, z]}}
  From the dimensions the solver adds known points: contact_fl/fr/rl/rr (tyre centre on the ground) and, when the
  tyre diameters are given, wheel_fl/fr/rl/rr (wheel centres). L is the vehicle's left (Y < 0).
landmarks.json:
  {"points": {"name": [x, y, z]},
   "photos": {"<view>": {"image": "refs/photos/<file>", "width": W, "height": H,
                         "focal_px": F (optional, holds the focal length fixed),
                         "points": {"name": [u, v] or [u, v, sigma_px]}}}}
  Width and height may be left out when the image file can be read.

Unknowns per view: position, rotation and focal length; the optical centre stays at the image centre unless
--free-centre. The error at each known point is given in pixels and in millimetres at that point's depth.
"""
import os
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, Camera, EXIT_GATE, EXIT_OK, look_at, load_json, number, open_image,  # noqa: E402
                     rodrigues, run, save_json)

USAGE = ('python tools/solve_cameras.py <project> [--max-rms-mm 12] [--views a,b] [--free-centre] '
         '[--vehicle FILE] [--landmarks FILE] [--out FILE]')


def known_points(vehicle, landmarks):
    pts = {}
    dims = vehicle.get('dimensions', {}) if isinstance(vehicle, dict) else {}
    if not isinstance(dims, dict):
        raise BadInput('vehicle.json "dimensions" must be an object')
    wb, tf, tr = dims.get('wheelbase'), dims.get('track_front'), dims.get('track_rear')
    if wb is not None and tf is not None and tr is not None:
        wb, tf, tr = number(wb, 'wheelbase'), number(tf, 'track_front'), number(tr, 'track_rear')
        df, dr = dims.get('tyre_diameter_front'), dims.get('tyre_diameter_rear')
        for side, s in (('l', -1), ('r', 1)):
            pts['contact_f' + side] = [0.0, s * tf / 2, 0.0]
            pts['contact_r' + side] = [wb, s * tr / 2, 0.0]
            if df is not None:
                pts['wheel_f' + side] = [0.0, s * tf / 2, number(df, 'tyre_diameter_front') / 2]
            if dr is not None:
                pts['wheel_r' + side] = [wb, s * tr / 2, number(dr, 'tyre_diameter_rear') / 2]
    for src in (vehicle.get('points', {}), landmarks.get('points', {})):
        if not isinstance(src, dict):
            raise BadInput('"points" must be an object of name: [x, y, z]')
        for k, v in src.items():
            if not (isinstance(v, (list, tuple)) and len(v) == 3):
                raise BadInput('point %r must be [x, y, z] in mm' % k)
            pts[k] = [number(c, 'point %s' % k) for c in v]
    return pts


def view_observations(name, ph, pts, project):
    if not isinstance(ph, dict) or not isinstance(ph.get('points'), dict):
        raise BadInput('photo %r needs a "points" object' % name)
    w, h = ph.get('width'), ph.get('height')
    if (w is None or h is None) and 'size' in ph:
        w, h = ph['size']
    if w is None or h is None:
        if not ph.get('image'):
            raise BadInput('photo %r needs width and height or a readable image' % name)
        im = open_image(os.path.join(project, ph['image']), 'photo %r' % name)
        w, h = im.size
    w, h = int(number(w, 'width')), int(number(h, 'height'))
    if w < 2 or h < 2:
        raise BadInput('photo %r has an impossible size %dx%d' % (name, w, h))
    names, X, uv, sig = [], [], [], []
    for k, o in ph['points'].items():
        if k not in pts:
            raise BadInput('photo %r marks point %r whose place on the vehicle is not known' % (name, k))
        if not (isinstance(o, (list, tuple)) and len(o) in (2, 3)):
            raise BadInput('photo %r point %r must be [u, v] or [u, v, sigma_px]' % (name, k))
        names.append(k)
        X.append(pts[k])
        uv.append([number(o[0], 'u'), number(o[1], 'v')])
        sig.append(number(o[2], 'sigma') if len(o) == 3 else 1.0)
        if sig[-1] <= 0:
            raise BadInput('photo %r point %r has sigma <= 0' % (name, k))
    return dict(names=names, X=np.array(X, float), uv=np.array(uv, float), sigma=np.array(sig, float), w=w, h=h,
                focal=ph.get('focal_px'))


class Model:
    """Parameter vector: position (3), rotation vector applied to R0 (3), log focal (1, unless fixed), centre (2)."""

    def __init__(self, ob, R0, free_centre):
        self.ob, self.R0, self.free_centre = ob, R0, free_centre
        self.fixed_f = None if ob['focal'] is None else float(ob['focal'])

    def unpack(self, p):
        C = p[0:3]
        R = rodrigues(p[3:6]) @ self.R0
        i = 6
        if self.fixed_f is None:
            f = float(np.exp(p[i]))
            i += 1
        else:
            f = self.fixed_f
        if self.free_centre:
            cx, cy = p[i], p[i + 1]
        else:
            cx, cy = (self.ob['w'] - 1) / 2.0, (self.ob['h'] - 1) / 2.0
        return Camera(C, R, f, cx, cy, self.ob['w'], self.ob['h'])

    def pack(self, C, f, cx=None, cy=None):
        p = list(C) + [0.0, 0.0, 0.0]
        if self.fixed_f is None:
            p.append(np.log(f))
        if self.free_centre:
            p += [cx if cx is not None else (self.ob['w'] - 1) / 2.0, cy if cy is not None else (self.ob['h'] - 1) / 2.0]
        return np.array(p, float)

    def residuals(self, p):
        cam = self.unpack(p)
        Xc = cam.cam_coords(self.ob['X'])
        z = Xc[:, 2]
        zs = np.where(z > 1.0, z, 1.0)
        pr = np.stack([cam.cx + cam.f * Xc[:, 0] / zs, cam.cy + cam.f * Xc[:, 1] / zs], 1)
        r = ((pr - self.ob['uv']) / self.ob['sigma'][:, None]).ravel()
        behind = np.maximum(0.0, 10.0 - z)            # points must be in front of the camera
        return np.concatenate([r, behind])


def dlt_start(ob):
    """Direct linear transform from >= 6 non-coplanar points. Returns (C, R, f) or None."""
    X, uv = ob['X'], ob['uv']
    if len(X) < 6:
        return None
    m = X.mean(0)
    s = np.sqrt(((X - m) ** 2).sum(1).mean())
    if s < 1e-6:
        return None
    Xn = np.c_[(X - m) / s, np.ones(len(X))]
    c2, s2 = uv.mean(0), max(np.sqrt(((uv - uv.mean(0)) ** 2).sum(1).mean()), 1e-6)
    un = (uv - c2) / s2
    A = []
    for Xi, (u, v) in zip(Xn, un):
        A.append(np.r_[Xi, np.zeros(4), -u * Xi])
        A.append(np.r_[np.zeros(4), Xi, -v * Xi])
    _, sv, Vt = np.linalg.svd(np.array(A))
    if sv[-2] < 1e-9 * sv[0]:
        return None
    Pn = Vt[-1].reshape(3, 4)
    T2 = np.array([[s2, 0, c2[0]], [0, s2, c2[1]], [0, 0, 1]])
    T3 = np.array([[1 / s, 0, 0, -m[0] / s], [0, 1 / s, 0, -m[1] / s], [0, 0, 1 / s, -m[2] / s], [0, 0, 0, 1]])
    P = T2 @ Pn @ T3
    M = P[:, :3]
    if abs(np.linalg.det(M)) < 1e-12:
        return None
    from scipy.linalg import rq
    K, R = rq(M)
    D = np.diag(np.sign(np.diag(K)))
    K, R = K @ D, D @ R
    if np.linalg.det(R) < 0:
        R = -R
    C = -np.linalg.solve(M, P[:, 3])
    f = (K[0, 0] + K[1, 1]) / 2 / K[2, 2]
    if not np.isfinite(f) or f <= 0:
        return None
    return C, R, abs(f)


def solve_view(ob, free_centre):
    X = ob['X']
    centre = X.mean(0)
    extent = max(np.sqrt(((X - centre) ** 2).sum(1)).max(), 100.0)
    w = ob['w']
    starts = []
    d = dlt_start(ob)
    if d is not None:
        starts.append(d)
    fs = [ob['focal']] if ob['focal'] is not None else [0.6 * w, 1.2 * w, 2.5 * w, 5.0 * w]
    for f in fs:
        dist = f * 2 * extent / (0.6 * w)
        for el in (5.0, 25.0, 55.0):
            for az in range(0, 360, 30):
                a, e = np.radians(az), np.radians(el)
                C = centre + dist * np.array([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])
                starts.append((C, look_at(C, centre), f))
    best = None
    for i, (C, R0, f) in enumerate(starts):
        m = Model(ob, R0, free_centre)
        try:
            r = least_squares(m.residuals, m.pack(C, f), method='trf', x_scale='jac', max_nfev=60)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if best is None or r.cost < best[0]:
            best = (r.cost, m, r.x)
        if i == 0 and d is not None and np.sqrt(2 * r.cost / len(X)) < 3.0:
            break                                   # the linear start already fits; no need for the grid
    if best is None:
        raise BadInput('no camera could be started for this view')
    _, m, x = best
    r = least_squares(m.residuals, x, method='trf', x_scale='jac', loss='soft_l1', f_scale=2.0, max_nfev=400)
    r = least_squares(m.residuals, r.x, method='trf', x_scale='jac', max_nfev=400)
    return m.unpack(r.x), len(r.x)


def report(cam, ob):
    pr = cam.project(ob['X'])
    d = pr - ob['uv']
    e_px = np.hypot(d[:, 0], d[:, 1])
    e_mm = e_px * cam.depth(ob['X']) / cam.f
    pts = {n: dict(px=float(a), mm=float(b), du=float(dd[0]), dv=float(dd[1]))
           for n, a, b, dd in zip(ob['names'], e_px, e_mm, d)}
    return dict(rms_px=float(np.sqrt(np.mean(e_px ** 2))), max_px=float(e_px.max()),
                rms_mm=float(np.sqrt(np.mean(e_mm ** 2))), max_mm=float(e_mm.max()), points=pts)


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('project')
    ap.add_argument('--max-rms-mm', type=float, default=12.0)
    ap.add_argument('--views', default=None, help='comma separated subset of views')
    ap.add_argument('--free-centre', action='store_true', help='also solve the optical centre')
    ap.add_argument('--vehicle')
    ap.add_argument('--landmarks')
    ap.add_argument('--out')
    a = ap.parse(argv)
    if not os.path.isdir(a.project):
        raise BadInput('project folder not found: %s' % a.project)
    vehicle = load_json(a.vehicle or os.path.join(a.project, 'data', 'vehicle.json'), 'vehicle.json')
    lm = load_json(a.landmarks or os.path.join(a.project, 'data', 'landmarks.json'), 'landmarks.json')
    if not isinstance(vehicle, dict) or not isinstance(lm, dict):
        raise BadInput('vehicle.json and landmarks.json must hold JSON objects')
    photos = lm.get('photos')
    if not isinstance(photos, dict) or not photos:
        raise BadInput('landmarks.json has no "photos"')
    views = list(photos) if not a.views else [v.strip() for v in a.views.split(',') if v.strip()]
    for v in views:
        if v not in photos:
            raise BadInput('view %r is not in landmarks.json' % v)
    pts = known_points(vehicle, lm)
    out = {'units': 'mm', 'convention': 'X_cam = R (X - C); camera x right, y down, z forward; '
           'pixel centres at integers, origin top-left', 'max_rms_mm': a.max_rms_mm, 'cameras': {}}
    ok = True
    for v in views:
        ob = view_observations(v, photos[v], pts, a.project)
        need = 4 + (1 if a.free_centre else 0) - (1 if ob['focal'] is not None else 0)
        if len(ob['names']) < need:
            raise BadInput('view %r has %d known points; at least %d are needed' % (v, len(ob['names']), need))
        cam, nparam = solve_view(ob, a.free_centre)
        rep = report(cam, ob)
        passed = rep['rms_mm'] <= a.max_rms_mm
        ok &= passed
        entry = cam.as_dict()
        if photos[v].get('image'):
            entry['image'] = photos[v]['image']
        entry.update(errors=rep, points_used=len(ob['names']), redundancy=2 * len(ob['names']) - nparam,
                     focal_fixed=ob['focal'] is not None, centre_free=bool(a.free_centre), passed=passed)
        out['cameras'][v] = entry
        print('%-16s n=%2d  rms %.2f px  %.1f mm  max %.1f mm  f=%.0f px  %s'
              % (v, len(ob['names']), rep['rms_px'], rep['rms_mm'], rep['max_mm'], cam.f, 'pass' if passed else 'FAIL'))
    out['passed'] = bool(ok)
    dst = a.out or os.path.join(a.project, 'data', 'cameras.json')
    save_json(dst, out)
    print('wrote', dst)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
