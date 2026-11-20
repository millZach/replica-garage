"""Measure the model's overall dimensions against the maker's figures.                    (runs in Blender)

usage: blender -b <scene.blend> --python tools/dimensions.py -- --vehicle data/vehicle.json --out DIR
       [--max-error-mm 10] [--wheels FL,FR,RL,RR] [--objects globs] [--exclude globs] [--width-exclude globs]
       [--only length,width,...]

Writes <out>/dimensions.json: length, width, height, wheelbase, front and rear track (and width_mirrors when the
maker gives it), each with the measured value, the maker's figure from vehicle.json "dimensions" and the error in
mm. Measured on the evaluated geometry of every rendering object (or --objects). Width leaves out --width-exclude
objects (mirrors, say); width_mirrors includes them. Height is the top above the ground plane Z = 0.
Wheels: --wheels names four objects (or globs) front-left, front-right, rear-left, rear-right. Without it, objects
with a custom property rg_wheel = "FL" / "FR" / "RL" / "RR" are used, else objects whose names contain wheel, tyre
or tire, split into four by position. A wheel's centre is the middle of its bounding box; the track is measured
between the wheels' middle planes.
Also reported (not judged): where the front axle sits in X (should be 0) and the lowest point (should be 0).
Exit 1 when a judged dimension is off by more than --max-error-mm or cannot be measured, 2 on bad input.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, number, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/dimensions.py -- --vehicle data/vehicle.json --out DIR '
         '[--max-error-mm 10] [--wheels FL,FR,RL,RR] [--width-exclude globs]')
KEYS = ('length', 'width', 'width_mirrors', 'height', 'wheelbase', 'track_front', 'track_rear')
CORNERS = ('FL', 'FR', 'RL', 'RR')


def wheel_groups(spec, geo):
    """{corner: [objects]} or None when no wheels can be found."""
    if spec:
        names = B.globs(spec)
        if len(names) != 4:
            raise BadInput('--wheels needs four names: front-left, front-right, rear-left, rear-right')
        out = {}
        for c, n in zip(CORNERS, names):
            obs = B.find_objects(n)
            if not obs:
                raise BadInput('wheel object %r not found' % n)
            out[c] = obs
        return out
    tagged = {}
    for ob in geo:
        t = str(ob.get('rg_wheel', '')).upper()
        if t in CORNERS:
            tagged.setdefault(t, []).append(ob)
    if len(tagged) == 4:
        return tagged
    cands = [ob for ob in geo if any(k in ob.name.lower() for k in ('wheel', 'tyre', 'tire'))]
    if len(cands) < 4:
        return None
    cen = {ob.name: np.mean(B.bbox([ob]), axis=0) for ob in cands}
    xs = np.array([c[0] for c in cen.values()])
    split = (xs.min() + xs.max()) / 2
    out = {}
    for ob in cands:
        c = cen[ob.name]
        key = ('F' if c[0] < split else 'R') + ('L' if c[1] < 0 else 'R')
        out.setdefault(key, []).append(ob)
    return out if len(out) == 4 else None


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--vehicle', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-error-mm', type=float, default=10.0)
    ap.add_argument('--wheels')
    ap.add_argument('--objects')
    ap.add_argument('--exclude')
    ap.add_argument('--width-exclude')
    ap.add_argument('--only')
    a = ap.parse(argv)
    veh = load_json(a.vehicle, 'vehicle.json')
    dims = veh.get('dimensions') if isinstance(veh, dict) else None
    if not isinstance(dims, dict):
        raise BadInput('vehicle.json has no "dimensions" object')
    maker = {k: number(dims[k], k) for k in KEYS if dims.get(k) is not None}
    only = B.globs(a.only) or list(KEYS)
    for k in only:
        if k not in KEYS:
            raise BadInput('unknown dimension %r (known: %s)' % (k, ', '.join(KEYS)))
    geo = B.visible_geometry(B.globs(a.objects) or None, B.globs(a.exclude) or None)
    if not geo:
        raise BadInput('no geometry to measure')
    s = B.mm_per_unit()
    dg = B.depsgraph()
    lo, hi = B.bbox(geo, dg)
    wx = B.globs(a.width_exclude)
    body = [o for o in geo if not (wx and B.match(o.name, wx))] or geo
    blo, bhi = B.bbox(body, dg)
    meas = dict(length=(hi[0] - lo[0]) * s, width=(bhi[1] - blo[1]) * s, width_mirrors=(hi[1] - lo[1]) * s,
                height=hi[2] * s)
    wheels = wheel_groups(a.wheels, geo)
    centres = {}
    if wheels:
        for c, obs in wheels.items():
            wlo, whi = B.bbox(obs, dg)
            centres[c] = ((wlo + whi) / 2 * s).tolist()
        W = {c: np.array(v) for c, v in centres.items()}
        meas['wheelbase'] = (W['RL'][0] + W['RR'][0]) / 2 - (W['FL'][0] + W['FR'][0]) / 2
        meas['track_front'] = W['FR'][1] - W['FL'][1]
        meas['track_rear'] = W['RR'][1] - W['RL'][1]
    rows, ok = {}, True
    for k in KEYS:
        m = meas.get(k)
        mk = maker.get(k)
        err = (m - mk) if (m is not None and mk is not None) else None
        judged = k in only and mk is not None
        passed = (err is not None and abs(err) <= a.max_error_mm) if judged else None
        if judged:
            ok &= bool(passed)
        rows[k] = dict(measured_mm=None if m is None else float(m), maker_mm=mk, error_mm=err, judged=judged,
                       passed=passed)
        if m is None and judged:
            rows[k]['note'] = 'no wheels found; name them with --wheels'
        print('%-14s measured %9s  maker %9s  error %8s  %s' % (
            k, '-' if m is None else '%.1f' % m, '-' if mk is None else '%.1f' % mk,
            '-' if err is None else '%+.1f' % err, '' if not judged else ('pass' if passed else 'FAIL')))
    front_x = (centres['FL'][0] + centres['FR'][0]) / 2 if centres else None
    res = dict(units='mm', max_error_mm=a.max_error_mm, dimensions=rows, wheel_centres_mm=centres,
               wheel_objects={c: [o.name for o in obs] for c, obs in (wheels or {}).items()},
               front_axle_x_mm=front_x, lowest_z_mm=float(lo[2] * s),
               bounds_mm=dict(min=(lo * s).tolist(), max=(hi * s).tolist()),
               objects=len(geo), width_excluded=[o.name for o in geo if o not in body], passed=bool(ok))
    save_json(os.path.join(a.out, 'dimensions.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
