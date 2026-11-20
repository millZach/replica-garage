"""Solve a camera for every photo and drawing from points whose place on the vehicle is known.

usage: python tools/solve_cameras.py [--project DIR] [--vehicle FILE] [--landmarks FILE] [--out FILE]
                                     [--max-rms-mm N] [--min-precise 3] [--free-centre]
                                     [--triangulate PIXELS_FILE]

Files default to <project>/data/vehicle.json, landmarks.json and cameras.json; --project defaults to the folder
above this tools/ folder. Formats are in CONTRACT.md. Named points (contact_*, hub_*, rim_*_*, front_extreme,
rear_extreme, roof_top, side_extreme_l/r) are worked out from vehicle.json's dimensions; points in its "points"
are taken as given. For front_extreme, rear_extreme, roof_top and side_extreme_* only one coordinate is known: the
other two are solved with the cameras, shared by every view that marks the point. A view's steer_deg turns the
front hub and rim points about the wheel's vertical axis.

A photo solves to a perspective camera: position, rotation, focal length (held at focal_mm / sensor_mm x the
file's width when both are given) and the optical centre at the middle of the file (solved too with
--free-centre). A drawing solves to an orthographic camera: rotation, scale and placement. Every view needs six or
more points. Each view's error at its known points is given in px and in mm on the vehicle; a view is graded
precise when its RMS is within the camera limit (--max-rms-mm, else camera_rms_mm in data/limits.json, else
tools/default_limits.json), otherwise visual. A photo whose fully known points all lie in one plane (thinner than
a tenth of their spread) is graded visual unless its focal length is given: its distance does not solve.
Exit 0 when at least --min-precise views are precise, 1 when fewer, 2 on bad input.

--triangulate takes a pixels file (a list of {"name", "view", "u", "v"}, file pixels) and the solved cameras, and
for each name seen in two or more views prints its position on the vehicle and how far off it lands in each
view; the result is also written beside the pixels file as <pixels>-triangulated.json.
"""
import os
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, Camera, EXIT_GATE, EXIT_OK, OrthoCamera, look_at, load_json,  # noqa: E402
                     number, open_image, project_limits, rodrigues, run, save_json)

USAGE = ('python tools/solve_cameras.py [--project DIR] [--max-rms-mm N] [--min-precise 3] [--free-centre] '
         '[--triangulate PIXELS_FILE]')
TOOLS = os.path.dirname(os.path.abspath(__file__))
MIN_POINTS = 6
PLANAR = 0.1
PARTIAL = {'front_extreme': 0, 'rear_extreme': 0, 'roof_top': 2, 'side_extreme_l': 1, 'side_extreme_r': 1}


def camera_limit(project, given):
    return given if given is not None else project_limits(project)[0]['camera_rms_mm']


# ------------------------------------------------------------------ points

def dims_of(vehicle):
    d = vehicle.get('dimensions', {}) if isinstance(vehicle, dict) else {}
    if not isinstance(d, dict):
        raise BadInput('vehicle.json "dimensions" must be an object')
    return {k: number(v, k) for k, v in d.items() if v is not None and not isinstance(v, (list, dict, str))}


def named_points(vehicle):
    """(fully known points, partly known points {name: (axis, value)}, guesses for partial points)."""
    d = dims_of(vehicle)
    full, part = {}, {}
    axle = {'f': 0.0, 'r': d.get('wheelbase')}
    track = {'f': d.get('track_front'), 'r': d.get('track_rear')}
    for e in ('f', 'r'):
        tw, td = d.get('tyre_width_' + ('front' if e == 'f' else 'rear')), d.get(
            'tyre_diameter_' + ('front' if e == 'f' else 'rear'))
        rd = d.get('rim_diameter_' + ('front' if e == 'f' else 'rear'))
        for side, sg in (('l', -1.0), ('r', 1.0)):
            k = e + side
            if axle[e] is None or track[e] is None:
                continue
            full['contact_' + k] = [axle[e], sg * track[e] / 2, 0.0]
            if tw is None or td is None:
                continue
            hub = np.array([axle[e], sg * (track[e] / 2 + tw / 2), td / 2])
            full['hub_' + k] = hub.tolist()
            if rd is not None:
                r = rd / 2
                full['rim_top_' + k] = (hub + [0, 0, r]).tolist()
                full['rim_bottom_' + k] = (hub - [0, 0, r]).tolist()
                full['rim_front_' + k] = (hub - [r, 0, 0]).tolist()
                full['rim_rear_' + k] = (hub + [r, 0, 0]).tolist()
    of, L, H, W = d.get('overhang_front'), d.get('length'), d.get('height'), d.get('width')
    if of is not None:
        part['front_extreme'] = (0, -of)
        if L is not None:
            part['rear_extreme'] = (0, L - of)
    if H is not None:
        part['roof_top'] = (2, H)
    if W is not None:
        part['side_extreme_l'] = (1, -W / 2)
        part['side_extreme_r'] = (1, W / 2)
    x0 = -of if of is not None else -0.2 * (d.get('wheelbase') or 2500.0)
    x1 = (L - of) if (L is not None and of is not None) else 1.2 * (d.get('wheelbase') or 2500.0)
    h = H or 1400.0
    guess = {'front_extreme': [x0, 0.0, 0.4 * h], 'rear_extreme': [x1, 0.0, 0.5 * h],
             'roof_top': [(x0 + x1) / 2, 0.0, h], 'side_extreme_l': [(x0 + x1) / 2, -(W or 1800) / 2, 0.45 * h],
             'side_extreme_r': [(x0 + x1) / 2, (W or 1800) / 2, 0.45 * h]}
    pts = vehicle.get('points', {}) if isinstance(vehicle, dict) else {}
    if not isinstance(pts, dict):
        raise BadInput('vehicle.json "points" must be an object of name: [x, y, z]')
    for k, v in pts.items():
        if not (isinstance(v, (list, tuple)) and len(v) == 3):
            raise BadInput('point %r must be [x, y, z] in mm' % k)
        full[k] = [number(c, 'point %s' % k) for c in v]
        part.pop(k, None)
    return full, part, guess, d


def steered(name, X, steer_deg, track_front):
    """Front hub and rim points turned by the view's steering angle about the wheel's vertical axis."""
    if not steer_deg or not (name.startswith('hub_f') or name.startswith('rim_')) or track_front is None:
        return X
    if name.startswith('rim_') and not name.split('_')[-1].startswith('f'):
        return X
    side = name.split('_')[-1]
    if side not in ('fl', 'fr'):
        return X
    a = -np.radians(steer_deg)
    p = np.array([0.0, (-1 if side == 'fl' else 1) * track_front / 2, 0.0])
    Rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    return (Rz @ (np.asarray(X) - p) + p).tolist()


# ------------------------------------------------------------------ views

def read_views(lm, project, full, part, dims):
    if not isinstance(lm, list) or not lm:
        raise BadInput('landmarks.json must be a non-empty list of views')
    views, seen = [], set()
    for i, e in enumerate(lm):
        if not isinstance(e, dict) or not e.get('view') or not e.get('file'):
            raise BadInput('landmarks entry %d needs "view" and "file"' % (i + 1))
        v = str(e['view'])
        if v in seen:
            raise BadInput('view %r is listed twice' % v)
        seen.add(v)
        kind = e.get('kind', 'photo')
        if kind not in ('photo', 'drawing'):
            raise BadInput('view %r: kind must be photo or drawing' % v)
        path = e['file'] if os.path.isabs(e['file']) else os.path.join(project, e['file'])
        im = open_image(path, 'file of view %r' % v)
        W, H = im.size
        u0, v0, u1, v1 = 0, 0, W, H
        if e.get('crop') is not None:
            try:
                u0, v0, u1, v1 = [int(round(number(c, 'crop'))) for c in e['crop']]
            except (TypeError, ValueError):
                raise BadInput('view %r: crop must be [u0, v0, u1, v1]' % v)
            if not (0 <= u0 < u1 <= W and 0 <= v0 < v1 <= H):
                raise BadInput('view %r: crop lies outside the %dx%d file' % (v, W, H))
        steer = number(e.get('steer_deg', 0.0), 'steer_deg')
        pts = e.get('points')
        if not isinstance(pts, dict):
            raise BadInput('view %r needs a "points" object' % v)
        if len(pts) < MIN_POINTS:
            raise BadInput('view %r has %d points; at least %d spread across the picture are needed'
                           % (v, len(pts), MIN_POINTS))
        names, uv = [], []
        for k, o in pts.items():
            if k not in full and k not in part:
                raise BadInput('view %r marks %r, which is not a known point (its dimensions may be missing)'
                               % (v, k))
            if not (isinstance(o, (list, tuple)) and len(o) == 2):
                raise BadInput('view %r point %r must be [u, v]' % (v, k))
            names.append(k)
            uv.append([number(o[0], 'u') - u0, number(o[1], 'v') - v0])
        focal = None
        if kind == 'photo' and e.get('focal_mm') is not None and e.get('sensor_mm') is not None:
            fm, sm = number(e['focal_mm'], 'focal_mm'), number(e['sensor_mm'], 'sensor_mm')
            if fm <= 0 or sm <= 0:
                raise BadInput('view %r: focal_mm and sensor_mm must be positive' % v)
            focal = fm / sm * W
        X = [steered(k, full[k], steer, dims.get('track_front')) if k in full else None for k in names]
        views.append(dict(view=v, kind=kind, file=e['file'], crop=e.get('crop'), offset=(u0, v0),
                          w=u1 - u0, h=v1 - v0, centre=((W - 1) / 2.0 - u0, (H - 1) / 2.0 - v0), steer=steer,
                          names=names, uv=np.array(uv, float), X=X, focal=focal))
    return views


# ------------------------------------------------------------------ models

class View:
    """Parameter block of one view. Perspective: C(3), rotvec(3), log f (unless fixed), centre (2, if free).
    Orthographic: rotvec(3), log s, tu, tv."""

    def __init__(self, v, R0, free_centre):
        self.v, self.R0, self.free = v, R0, free_centre and v['kind'] == 'photo'
        self.ortho = v['kind'] == 'drawing'
        self.fixed_f = v['focal']

    def size(self):
        if self.ortho:
            return 6
        return 6 + (0 if self.fixed_f is not None else 1) + (2 if self.free else 0)

    def pack(self, C=None, f=None, s=None, t=(0.0, 0.0)):
        if self.ortho:
            return np.array([0.0, 0.0, 0.0, np.log(s), t[0], t[1]])
        p = list(C) + [0.0, 0.0, 0.0]
        if self.fixed_f is None:
            p.append(np.log(f))
        if self.free:
            p += list(self.v['centre'])
        return np.array(p, float)

    def project(self, p, X):
        X = np.atleast_2d(X)
        if self.ortho:
            R = rodrigues(p[0:3]) @ self.R0
            s = np.exp(p[3])
            return np.stack([s * X @ R[0] + p[4], s * X @ R[1] + p[5]], 1), np.full(len(X), 1.0 / s), None
        R = rodrigues(p[3:6]) @ self.R0
        i = 6
        if self.fixed_f is None:
            f = np.exp(p[i])
            i += 1
        else:
            f = self.fixed_f
        cx, cy = (p[i], p[i + 1]) if self.free else self.v['centre']
        Xc = (X - p[0:3]) @ R.T
        z = Xc[:, 2]
        zs = np.where(z > 1.0, z, 1.0)
        return np.stack([cx + f * Xc[:, 0] / zs, cy + f * Xc[:, 1] / zs], 1), zs / f, z

    def camera(self, p, centre_of_vehicle):
        w, h = self.v['w'], self.v['h']
        if self.ortho:
            R = rodrigues(p[0:3]) @ self.R0
            s = np.exp(p[3])
            cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
            a, b = (cx - p[4]) / s, (cy - p[5]) / s
            c = float(centre_of_vehicle @ R[2]) - 20000.0          # 20 m in front of the vehicle on the axis
            C = R[0] * a + R[1] * b + R[2] * c
            return OrthoCamera(C, R, s, cx, cy, w, h)
        R = rodrigues(p[3:6]) @ self.R0
        i = 6
        if self.fixed_f is None:
            f = np.exp(p[i])
            i += 1
        else:
            f = self.fixed_f
        cx, cy = (p[i], p[i + 1]) if self.free else self.v['centre']
        return Camera(p[0:3], R, f, cx, cy, w, h)


def residual_block(m, p, X, uv):
    pr, _, z = m.project(p, X)
    r = (pr - uv).ravel()
    if z is not None:
        r = np.concatenate([r, np.maximum(0.0, 10.0 - z)])
    return r


def dlt_start(X, uv):
    if len(X) < 6:
        return None
    m = X.mean(0)
    s = np.sqrt(((X - m) ** 2).sum(1).mean())
    if s < 1e-6:
        return None
    Xn = np.c_[(X - m) / s, np.ones(len(X))]
    c2 = uv.mean(0)
    s2 = max(np.sqrt(((uv - c2) ** 2).sum(1).mean()), 1e-6)
    un = (uv - c2) / s2
    A = []
    for Xi, (u, v) in zip(Xn, un):
        A.append(np.r_[Xi, np.zeros(4), -u * Xi])
        A.append(np.r_[np.zeros(4), Xi, -v * Xi])
    _, sv, Vt = np.linalg.svd(np.array(A))
    if sv[-2] < 1e-9 * sv[0]:
        return None
    P = np.array([[s2, 0, c2[0]], [0, s2, c2[1]], [0, 0, 1]]) @ Vt[-1].reshape(3, 4) @ np.array(
        [[1 / s, 0, 0, -m[0] / s], [0, 1 / s, 0, -m[1] / s], [0, 0, 1 / s, -m[2] / s], [0, 0, 0, 1]])
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
    return (C, R, abs(f)) if np.isfinite(f) and f > 0 else None


def init_perspective(v, X, free_centre):
    uv = v['uv']
    centre = X.mean(0)
    extent = max(np.sqrt(((X - centre) ** 2).sum(1)).max(), 100.0)
    w = v['w']
    starts = []
    d = dlt_start(X, uv)
    if d is not None:
        starts.append(d)
    fs = [v['focal']] if v['focal'] is not None else [0.6 * w, 1.2 * w, 2.5 * w, 5.0 * w]
    for f in fs:
        dist = f * 2 * extent / (0.6 * w)
        for el in (5.0, 25.0, 55.0):
            for az in range(0, 360, 30):
                a, e = np.radians(az), np.radians(el)
                C = centre + dist * np.array([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])
                starts.append((C, look_at(C, centre), f))
    best = None
    for i, (C, R0, f) in enumerate(starts):
        m = View(v, R0, free_centre)
        p0 = m.pack(C=C, f=f)
        try:
            r = least_squares(lambda p: residual_block(m, p, X, uv), p0, x_scale='jac', max_nfev=60)
        except (ValueError, np.linalg.LinAlgError):
            continue
        if best is None or r.cost < best[0]:
            best = (r.cost, m, r.x)
        if i == 0 and d is not None and np.sqrt(2 * r.cost / len(X)) < 3.0:
            break
    if best is None:
        raise BadInput('view %r: no camera could be started' % v['view'])
    return best[1], best[2]


def init_ortho(v, X):
    uv = v['uv']
    A = np.c_[X, np.ones(len(X))]
    sol, *_ = np.linalg.lstsq(A, uv, rcond=None)
    M = sol[:3].T                                   # 2 x 3: s * [r0; r1]
    U, S, Vt = np.linalg.svd(M, full_matrices=False)
    s = float(S.mean())
    if s <= 0:
        raise BadInput('drawing %r: points do not spread out' % v['view'])
    rows = U @ Vt
    R0 = np.stack([rows[0], rows[1], np.cross(rows[0], rows[1])])
    m = View(v, R0, False)
    p = m.pack(s=s, t=(sol[3, 0], sol[3, 1]))
    r = least_squares(lambda q: residual_block(m, q, X, uv), p, x_scale='jac', max_nfev=200)
    return m, r.x


def planar(Xfull):
    if len(Xfull) < 3:
        return True
    c = Xfull - Xfull.mean(0)
    s = np.linalg.svd(c, compute_uv=False)
    return bool(s[0] <= 0 or s[-1] / s[0] < PLANAR)


def solve(views, part, guess, free_centre):
    unknown = sorted({n for v in views for n in v['names'] if n in part})
    blocks = []
    for v in views:
        X = np.array([x if x is not None else guess[n] for n, x in zip(v['names'], v['X'])], float)
        m, p = init_ortho(v, X) if v['kind'] == 'drawing' else init_perspective(v, X, free_centre)
        blocks.append((m, p))
    sizes = [m.size() for m, _ in blocks]
    offs = np.cumsum([0] + sizes)
    q0 = np.concatenate([p for _, p in blocks] + [np.array([c for n in unknown for k, c in enumerate(guess[n])
                                                            if k != part[n][0]], float)])
    base = offs[-1]

    def points(q, v):
        X = []
        for n, x in zip(v['names'], v['X']):
            if x is not None:
                X.append(x)
            else:
                j = base + 2 * unknown.index(n)
                ax, val = part[n]
                free = [k for k in range(3) if k != ax]
                pt = [0.0, 0.0, 0.0]
                pt[ax], pt[free[0]], pt[free[1]] = val, q[j], q[j + 1]
                X.append(pt)
        return np.array(X, float)

    def fun(q):
        return np.concatenate([residual_block(m, q[offs[i]:offs[i + 1]], points(q, v), v['uv'])
                               for i, ((m, _), v) in enumerate(zip(blocks, views))])

    if unknown:
        r = least_squares(fun, q0, x_scale='jac', loss='soft_l1', f_scale=2.0, max_nfev=2000)
        r = least_squares(fun, r.x, x_scale='jac', max_nfev=2000)
        q = r.x
    else:
        q = q0
    solved = {n: points(q, dict(names=[n], X=[None])).tolist()[0] for n in unknown}
    out = []
    for i, ((m, _), v) in enumerate(zip(blocks, views)):
        out.append((m, q[offs[i]:offs[i + 1]], points(q, v)))
    return out, solved


def grade(m, p, X, v, limit, allX):
    pr, mmpp, _ = m.project(p, X)
    d = pr - v['uv']
    e_px = np.hypot(d[:, 0], d[:, 1])
    e_mm = e_px * mmpp
    rep = dict(rms_px=float(np.sqrt(np.mean(e_px ** 2))), rms_mm=float(np.sqrt(np.mean(e_mm ** 2))),
               max_px=float(e_px.max()), max_mm=float(e_mm.max()),
               points={n: dict(px=float(a), mm=float(b)) for n, a, b in zip(v['names'], e_px, e_mm)})
    known = np.array([x for x in v['X'] if x is not None], float)
    flat = v['kind'] == 'photo' and v['focal'] is None and planar(known)
    rep['planar'] = bool(flat)
    notes = []
    if flat:
        notes.append('every fully known point lies in one plane: the distance does not solve')
    if rep['rms_mm'] > limit:
        notes.append('error %.1f mm is over the %.1f mm limit' % (rep['rms_mm'], limit))
    rep['grade'] = 'visual' if notes else 'precise'
    rep['notes'] = notes
    return rep


# ------------------------------------------------------------------ triangulate

def triangulate(cams_file, pixels_file):
    d = load_json(cams_file, 'cameras file')
    cams = d.get('cameras') if isinstance(d, dict) else None
    if not isinstance(cams, dict) or not cams:
        raise BadInput('%s has no solved cameras' % cams_file)
    px = load_json(pixels_file, 'pixels file')
    if not isinstance(px, list) or not px:
        raise BadInput('pixels file must be a non-empty list of {name, view, u, v}')
    groups = {}
    for i, e in enumerate(px):
        if not isinstance(e, dict) or not all(k in e for k in ('name', 'view', 'u', 'v')):
            raise BadInput('pixels entry %d needs name, view, u and v' % (i + 1))
        if e['view'] not in cams:
            raise BadInput('view %r is not in %s' % (e['view'], cams_file))
        c = cams[e['view']]
        off = (c.get('crop') or [0, 0])[:2]
        groups.setdefault(str(e['name']), []).append(
            (e['view'], Camera.from_dict(c), np.array([number(e['u'], 'u') - off[0], number(e['v'], 'v') - off[1]])))
    out = {}
    for name, obs in groups.items():
        if len({o[0] for o in obs}) < 2:
            raise BadInput('%r is seen in only one view; two or more are needed' % name)
        A, b = np.zeros((3, 3)), np.zeros(3)
        for _, cam, uv in obs:
            o, dvec = cam.ray(uv)
            P = np.eye(3) - np.outer(dvec, dvec)
            A += P
            b += P @ o
        X0 = np.linalg.solve(A, b)
        r = least_squares(lambda X: np.concatenate([cam.project(X)[0] - uv for _, cam, uv in obs]), X0)
        X = r.x
        per = {}
        for view, cam, uv in obs:
            e = float(np.hypot(*(cam.project(X)[0] - uv)))
            per[view] = dict(px=e, mm=float(e * cam.mm_per_px(X)[0]))
        out[name] = dict(position_mm=X.tolist(), views=per)
        print('%-20s x %8.1f  y %8.1f  z %8.1f   ' % (name, X[0], X[1], X[2]) +
              '  '.join('%s %.1f px (%.1f mm)' % (k, v['px'], v['mm']) for k, v in per.items()))
    dst = os.path.splitext(pixels_file)[0] + '-triangulated.json'
    save_json(dst, dict(cameras=os.path.abspath(cams_file), points=out))
    return EXIT_OK


# ------------------------------------------------------------------ main

def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--project', default=os.path.dirname(TOOLS))
    ap.add_argument('--vehicle')
    ap.add_argument('--landmarks')
    ap.add_argument('--out')
    ap.add_argument('--max-rms-mm', type=float)
    ap.add_argument('--min-precise', type=int, default=3)
    ap.add_argument('--free-centre', action='store_true')
    ap.add_argument('--triangulate')
    a = ap.parse(argv)
    project = os.path.abspath(a.project)
    if not os.path.isdir(project):
        raise BadInput('project folder not found: %s' % project)
    dst = a.out or os.path.join(project, 'data', 'cameras.json')
    if a.triangulate:
        return triangulate(dst, a.triangulate)
    vehicle = load_json(a.vehicle or os.path.join(project, 'data', 'vehicle.json'), 'vehicle.json')
    lm = load_json(a.landmarks or os.path.join(project, 'data', 'landmarks.json'), 'landmarks.json')
    full, part, guess, dims = named_points(vehicle)
    limit = camera_limit(project, a.max_rms_mm)
    views = read_views(lm, project, full, part, dims)
    solved, partial = solve(views, part, guess, a.free_centre)
    allX = np.array(list(full.values()) or [[0, 0, 0]], float)
    centre = allX.mean(0)
    res = {'units': 'mm', 'convention': 'X_cam = R (X - C); camera x right, y down, z forward; pixels of the '
           "view's picture (the file cut to its crop), centres at integers, origin top-left",
           'limit_mm': limit, 'min_precise': a.min_precise, 'cameras': {}, 'solved_points': partial}
    n_precise = 0
    for (m, p, X), v in zip(solved, views):
        cam = m.camera(p, centre)
        rep = grade(m, p, X, v, limit, allX)
        n_precise += rep['grade'] == 'precise'
        e = cam.as_dict()
        e.update(file=v['file'], crop=v['crop'], steer_deg=v['steer'], rms_mm=rep['rms_mm'], rms_px=rep['rms_px'],
                 max_mm=rep['max_mm'], grade=rep['grade'], planar=rep['planar'], notes=rep['notes'],
                 focal_fixed=v['focal'] is not None, points=rep['points'], kind_of_source=v['kind'])
        res['cameras'][v['view']] = e
        print('%-16s %-12s n=%2d  rms %6.2f px %7.1f mm  %s%s' % (
            v['view'], cam.kind, len(v['names']), rep['rms_px'], rep['rms_mm'], rep['grade'],
            ('  (' + '; '.join(rep['notes']) + ')') if rep['notes'] else ''))
    for n, X in partial.items():
        print('solved %-16s x %8.1f  y %8.1f  z %8.1f' % (n, X[0], X[1], X[2]))
    ok = n_precise >= a.min_precise
    res['precise_views'] = n_precise
    res['passed'] = bool(ok)
    save_json(dst, res)
    print('%d precise of %d views (need %d); wrote %s' % (n_precise, len(views), a.min_precise, dst))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
