"""The vehicle from all round, under a look and a presentation style.                    (runs in Blender)

usage: blender -b <scene.blend> --python tools/orbit.py -- --out DIR [--project DIR] [--look NAME]
       [--style showroom|studio|daylight] [--sky FILE] [--beauty] [--lens 85] [--height-mm 900] [--fill 0.85]
       [--resolution WxH] [--device CPU|GPU] [--gpu-type T] [--samples N] [--hide parts] [--min-coverage 0.95]

Ten views: eight evenly round the vehicle with the camera at --height-mm (about hip height), named by where the
camera stands (front, front-left, left, rear-left, rear, rear-right, right, front-right), and two from above,
40 degrees up (above-front-left, above-rear-right). Each is on a long lens (--lens, mm on a 36 mm sensor) and set
back until the vehicle's bounding box fills --fill of the picture's width or height (over 1 crops it: the view
then fails). --views renders a subset; coverage is still measured for all ten.
The look is --look (default the proof look in data/finishes.json); the style is --style, else "style" in
finishes.json, else showroom. daylight needs a sky image the project supplies: --sky, else "sky" in
finishes.json (a path under refs/).
Evidence quality by default: 1200 x 800, sampling and device from data/render.json, written by the first
evidence render as for render_views.py. --beauty renders at twice the size with four times the samples (at
least 256) and never writes data/render.json.
Writes <out>/<position>.png and <out>/orbit.json: each view's camera, target, direction, lens, picture size and
how much of the frame the vehicle fills; and the coverage of the vehicle's left and right sides, measured as in
closeups.py (both sides are checked, never assumed).
Exit 1 when a view does not have the whole vehicle inside its frame or a side is covered under --min-coverage;
2 on bad input.
"""
import math
import os
import sys

import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import closeups  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/orbit.py -- --out DIR [--project DIR] [--look NAME] '
         '[--style showroom|studio|daylight] [--beauty]')
RING = ('front', 'front-left', 'left', 'rear-left', 'rear', 'rear-right', 'right', 'front-right')
ABOVE = (('above-front-left', 'front-left'), ('above-rear-right', 'rear-right'))


def heading(name):
    """Unit vector from the vehicle toward where the camera stands (X rear, Y right)."""
    a = RING.index(name) * 45.0                       # 0 front (-X), 90 left (-Y), 180 rear, 270 right
    r = math.radians(a)
    return np.array([-math.cos(r), -math.sin(r), 0.0])


def frame_ratio(C, target, corners, tx, ty):
    fwd = target - C
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, (0, 0, 1.0))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    rel = corners - C
    z = rel @ fwd
    if np.any(z <= 0):
        return np.inf, np.inf
    return float(np.max(np.abs(rel @ right) / (z * tx))), float(np.max(np.abs(rel @ up) / (z * ty)))


def place(direction, target, corners, tx, ty, fill, height):
    """Camera position along `direction` from the target (at `height` when not None) that frames the corners."""
    def at(d):
        C = target + direction * d
        if height is not None:
            C = np.array([C[0], C[1], height])
        return C

    lo, hi = 0.01, 1e4
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        fx, fy = frame_ratio(at(mid), target, corners, tx, ty)
        if max(fx, fy) > fill:
            lo = mid
        else:
            hi = mid
    return at(hi)


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--beauty', action='store_true')
    ap.add_argument('--lens', type=float, default=85.0)
    ap.add_argument('--height-mm', type=float, default=900.0)
    ap.add_argument('--fill', type=float, default=0.85)
    ap.add_argument('--resolution')
    ap.add_argument('--min-coverage', type=float, default=0.95)
    ap.add_argument('--samples-surface', type=int, default=3000)
    ap.add_argument('--views', default='', help='render only these views (coverage is still measured for all ten)')
    B.add_project_arg(ap)
    B.add_render_args(ap)
    B.add_style_args(ap)
    a = ap.parse(argv)
    if a.mode and a.mode != 'lit':
        raise BadInput('orbit.py renders the look in a style; --mode is not used')
    if a.lens <= 0 or not 0.2 <= a.fill <= 1.5 or a.height_mm <= 0:
        raise BadInput('lens, fill (0.2 to 1.5) or height out of range')
    if a.resolution:
        try:
            W, H = [int(v) for v in a.resolution.lower().split('x')]
        except ValueError:
            raise BadInput('--resolution must look like 1200x800')
    else:
        W, H = (2400, 1600) if a.beauty else (1200, 800)
    if W < 8 or H < 8:
        raise BadInput('--resolution is too small')
    project = B.project_dir(a)
    settings_path = os.path.join(project, 'data', 'render.json')
    s, ignored, write_to = B.render_settings(a, settings_path)
    if a.beauty:
        write_to = None
        s['samples'] = a.samples if a.samples is not None else max(256, 4 * int(s['samples']))
    finishes = B.load_finishes(project)
    style, sky = B.resolve_style(a, finishes, project, default='showroom')
    hidden = B.hide_objects(B.globs(a.hide))
    geo = B.visible_geometry()
    if not geo:
        raise BadInput('the scene has no visible geometry')
    u = B.mm_per_unit()
    lo, hi = B.bbox(geo)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    target = (lo + hi) / 2
    tx = 18.0 / a.lens
    ty = tx * H / W
    views = []
    for name in RING:
        C = place(heading(name), target, corners, tx, ty, a.fill, a.height_mm / u)
        views.append(dict(name=name, camera=C))
    for name, base in ABOVE:
        e = math.radians(40.0)
        d = heading(base) * math.cos(e) + np.array([0, 0, math.sin(e)])
        views.append(dict(name=name, camera=place(d, target, corners, tx, ty, a.fill, None)))
    for v in views:
        fwd = target - v['camera']
        v.update(centre=target, direction=fwd / np.linalg.norm(fwd), up=np.array([0, 0, 1.0]), tan=(tx, ty))
        v['fill'] = frame_ratio(v['camera'], target, corners, tx, ty)
    far = float(np.linalg.norm(hi - lo)) * 4 + max(float(np.linalg.norm(v['camera'] - target)) for v in views) * 2
    stats = closeups.coverage(geo, views, math.atan(tx), ['left', 'right'], a.samples_surface, eps=0.5 / u, far=far)
    ok = True
    for r, st in stats.items():
        st['passed'] = st['fraction'] is not None and st['fraction'] >= a.min_coverage
        ok &= st['passed']
        print('COVER %-6s exposed %5d  covered %5.1f%%  %s' % (r, st['exposed'], 100 * (st['fraction'] or 0),
                                                             'pass' if st['passed'] else 'FAIL'))
    dev = B.setup_render(s)
    look = B.apply_style(style, sky, a.look, finishes, lo, hi)
    os.makedirs(a.out, exist_ok=True)
    only = B.globs(a.views)
    for n in only:
        if n not in RING + tuple(x for x, _ in ABOVE):
            raise BadInput('unknown view %r' % n)
    rows = []
    for v in views:
        if only and v['name'] not in only:
            continue
        cam = B.look_camera('rg orbit ' + v['name'], v['camera'], target, (0, 0, 1), a.lens, (W, H))
        cam.data.sensor_fit = 'HORIZONTAL'
        px = [B.project_px(cam, X, W, H) for X in corners]
        inside = all(-0.5 <= p[0] <= W - 0.5 and -0.5 <= p[1] <= H - 0.5 and z > 0 for p, z in px)
        uv = np.array([p for p, _ in px])
        fill = float(max(np.ptp(uv[:, 0]) / W, np.ptp(uv[:, 1]) / H))
        f = os.path.join(os.path.abspath(a.out), v['name'] + '.png')
        B.render_to(f)
        good = inside and fill >= 0.5
        ok &= good
        rows.append(dict(name=v['name'], file=f, camera_mm=(v['camera'] * u).tolist(), target_mm=(target * u).tolist(),
                         direction=v['direction'].tolist(), up=[0.0, 0.0, 1.0], lens_mm=a.lens, sensor_mm=36.0,
                         resolution=[W, H], vehicle_inside=bool(inside), fill=fill, passed=bool(good)))
        print('VIEW %-17s fill %.2f  %s' % (v['name'], fill, 'pass' if good else 'FAIL (vehicle not inside the frame)'))
    B.write_settings(write_to, s, dev)
    res = dict(style=style, sky=sky, look=look, beauty=a.beauty, settings=dict(s, **dev), ignored_arguments=ignored,
               hidden=hidden, views=rows, coverage=stats, min_coverage=a.min_coverage, passed=bool(ok))
    save_json(os.path.join(a.out, 'orbit.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
