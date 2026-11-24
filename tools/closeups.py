"""A ring of close views over both sides, the front, the rear and the roof, with coverage measured. (Blender)

usage: blender -b <scene.blend> --python tools/closeups.py -- --out DIR [--project DIR] [--size-mm 600]
       [--mode lit|clay|zebra] [--look NAME] [--hide parts] [--resolution 800] [--lens 50] [--overlap 0.25]
       [--regions left,right,front,rear,roof] [--skip-regions R] [--min-coverage 0.95] [--samples-surface 4000]
       [--no-render] [--device CPU|GPU] [--gpu-type T] [--samples N] [--style S] [--sky FILE]

This is the close-up ring. Mode defaults to lit, under the look (default the proof look in data/finishes.json)
and its studio. Sampling and device come from data/render.json, as for render_views.py. --hide a,b,c leaves
those registered parts out (names or globs), to look at what removed panels uncover; nested parts need all of
them. It runs on whatever scene it is given (out/vehicle.blend, a round's workshop.blend) and writes to --out.
--style showroom|studio|daylight (and --sky for daylight) renders the ring in a presentation style instead of the
look's evidence studio.

Each view frames a square of --size-mm on the surface, looking straight in along the region's axis. Views are laid
on a grid over each face of the vehicle's bounding box with --overlap between neighbours; each is aimed at the
surface a ray finds there, and is skipped where the ray finds nothing. Views are named by region and position in
mm, e.g. left-x+1200-z0450, right-x+1200-z0450, front-y-0300-z0600, rear-..., roof-x+1500-y+0000.
Writes <out>/<name>.png per view and <out>/closeups.json listing each view's centre, direction, camera position,
up vector, lens and resolution (rays.py can rebuild any of them), and the coverage.

Coverage is measured, never assumed: points are sampled over the whole surface, each is given to the region its
normal faces most (left -Y, right +Y, front -X, rear +X, roof +Z; undersides are not counted) and kept when it can
be seen from outside at all. A point is covered when some view has it in frame, facing the camera within 75
degrees, with nothing in front of it. --skip-regions leaves a region's views out (a quick partial ring) but its
coverage is still measured, so a ring that misses a side fails.
Exit 1 when any region in --regions is under --min-coverage, 2 on bad input.
"""
import math
import os
import sys

import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/closeups.py -- --out DIR [--project DIR] [--size-mm 600] '
         '[--mode lit|clay|zebra] [--look NAME] [--hide parts] [--min-coverage 0.95] [--no-render]')
REGIONS = {  # name: (look direction, the two in-plane axes used for the grid and the name, up vector)
    'left': ((0, 1, 0), (0, 2), (0, 0, 1)),
    'right': ((0, -1, 0), (0, 2), (0, 0, 1)),
    'front': ((1, 0, 0), (1, 2), (0, 0, 1)),
    'rear': ((-1, 0, 0), (1, 2), (0, 0, 1)),
    'roof': ((0, 0, -1), (0, 1), (-1, 0, 0)),
}
AXIS = 'xyz'
FACING_COS = math.cos(math.radians(75))


def grid(lo, hi, size, step):
    ext = hi - lo
    if ext <= size:
        return [(lo + hi) / 2]
    n = int(math.ceil((ext - size) / step)) + 1
    return list(np.linspace(lo + size / 2, hi - size / 2, n))


def plan(lo, hi, size, overlap, lens, res, regions, unit):
    sc = B.bpy.context.scene
    dg = B.depsgraph()
    step = size * (1 - overlap)
    half = math.atan(18.0 / lens)                              # 36 mm sensor, square frame
    dist = (size / 2) / math.tan(half)
    views = []
    span = float(np.max(hi - lo)) + 4 * dist
    for reg in regions:
        look, (a1, a2), up = REGIONS[reg]
        look = np.array(look, float)
        k = int(np.flatnonzero(look)[0])
        start = (lo[k] - dist) if look[k] > 0 else (hi[k] + dist)
        for u in grid(lo[a1], hi[a1], size, step):
            for v in grid(lo[a2], hi[a2], size, step):
                o = np.zeros(3)
                o[a1], o[a2], o[k] = u, v, start
                hit, loc, nor, *_ = sc.ray_cast(dg, Vector(o), Vector(look), distance=span)
                if not hit:
                    continue
                c = np.array(loc)
                cam = c - look * dist
                name = '%s-%s%+05d-%s%04d' % (reg, AXIS[a1], round(u * unit), AXIS[a2], round(v * unit)) \
                    if a2 == 2 else '%s-%s%+05d-%s%+05d' % (reg, AXIS[a1], round(u * unit), AXIS[a2], round(v * unit))
                views.append(dict(name=name, region=reg, centre=c, camera=cam, direction=look, up=np.array(up, float)))
    return views, dist, half


def replay_ring(path, regions, unit, size_mm, overlap, lens):
    source = load_json(path, 'baseline close-up cameras')
    src_size = float(source['size_mm'])
    src_overlap = float(source['overlap'])
    if size_mm is not None and abs(src_size - size_mm) > 1e-6:
        raise BadInput('baseline close-up size_mm (%g) differs from requested --size-mm (%g)' % (src_size, size_mm))
    if overlap is not None and abs(src_overlap - overlap) > 1e-6:
        raise BadInput('baseline close-up overlap (%g) differs from requested --overlap (%g)' % (src_overlap, overlap))
    size_mm = src_size if size_mm is None else size_mm
    overlap = src_overlap if overlap is None else overlap
    views = []
    for row in source['views']:
        if row['region'] not in regions:
            continue
        if row['lens_mm'] != lens or row['sensor_mm'] != 36 or row['resolution'][0] != row['resolution'][1]:
            raise BadInput('baseline close-up intrinsics differ from the requested square-frame camera')
        views.append(dict(name=row['name'], region=row['region'], centre=np.asarray(row['centre_mm']) / unit,
                          camera=np.asarray(row['camera_mm']) / unit, direction=np.asarray(row['direction']),
                          up=np.asarray(row['up'])))
    if not views or {v['region'] for v in views} != set(regions):
        raise BadInput('baseline close-up poses do not cover all requested regions')
    half = math.atan(18.0 / lens)
    return views, size_mm / (2 * unit * math.tan(half)), half, size_mm, overlap


def sample_surface(objs, n, rng, with_owners=False, outer_only=True):
    """Area-weighted points and unit normals over exterior/outer triangles (scene units)."""
    P, N, A, owners = [], [], [], []
    for ob in objs:
        md = B.MeshData(ob, layers=outer_only)
        tris = md.outer_tris() if outer_only else md.tris
        if not len(tris):
            continue
        v = md.verts[tris]
        cr = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        area = np.linalg.norm(cr, axis=1) / 2
        nrm = cr / np.maximum(2 * area, 1e-30)[:, None]
        P.append(v)
        N.append(nrm)
        A.append(area)
        owners.append(ob.name)
    if not P:
        raise BadInput('no surface to sample')
    ends = np.cumsum([len(a) for a in A])
    P, N, A = np.concatenate(P), np.concatenate(N), np.concatenate(A)
    tot = A.sum()
    if tot <= 0:
        raise BadInput('the surface has no area')
    idx = rng.choice(len(A), size=n, p=A / tot)
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    w = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    pts = (P[idx] * w[:, :, None]).sum(1)
    if with_owners:
        return pts, N[idx], np.asarray(owners)[np.searchsorted(ends, idx, side='right')]
    return pts, N[idx]


def tilt_dirs(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    t1 = np.cross(n, a)
    t1 /= np.linalg.norm(t1)
    t2 = np.cross(n, t1)
    c = math.cos(math.radians(45))
    return [n] + [c * n + c * t for t in (t1, -t1, t2, -t2)]


def escapes(p, d, eps, far):
    sc = B.bpy.context.scene
    hit, *_ = sc.ray_cast(B.depsgraph(), Vector(p + d * eps), Vector(d), distance=far)
    return not hit


def coverage(objs, views, half, regions_measured, n_samples, eps, far):
    sc = B.bpy.context.scene
    dg = B.depsgraph()
    rng = np.random.default_rng(0)
    pts, nrm, owners = sample_surface(objs, n_samples, rng, with_owners=True, outer_only=True)
    dirs = {'left': (0, -1, 0), 'right': (0, 1, 0), 'front': (-1, 0, 0), 'rear': (1, 0, 0), 'roof': (0, 0, 1)}
    names = list(dirs)
    D = np.array([dirs[k] for k in names], float)
    t = math.tan(half)
    stats = {r: dict(samples=0, exposed=0, covered=0) for r in regions_measured}
    missed = {r: {} for r in regions_measured}
    units = B.mm_per_unit()
    cams = [(np.array(v['camera']), np.array(v['direction']), np.array(v['up']), v.get('tan', (t, t)))
            for v in views]
    for p, n, owner in zip(pts, nrm, owners):
        out_pos = any(escapes(p, d, eps, far) for d in tilt_dirs(n))
        if not out_pos:                 # normals may point inward: try the other side
            n = -n
            if not any(escapes(p, d, eps, far) for d in tilt_dirs(n)):
                reg = names[int(np.argmax(D @ -n))] if np.max(D @ -n) > 0 else None
                if reg in stats:
                    stats[reg]['samples'] += 1
                continue
        score = D @ n
        if score.max() <= 1e-6 or n[2] < -0.7:
            continue                    # faces downward: underside, not counted
        reg = names[int(np.argmax(score))]
        if reg not in stats:
            continue
        st = stats[reg]
        st['samples'] += 1
        st['exposed'] += 1
        for C, fwd, up, (tx, ty) in cams:
            rel = p - C
            z = rel @ fwd
            if z <= 0:
                continue
            right = np.cross(fwd, up)
            right /= np.linalg.norm(right)
            upv = np.cross(right, fwd)
            if abs(rel @ right) > tx * z or abs(rel @ upv) > ty * z:
                continue
            to_cam = -rel / np.linalg.norm(rel)
            if n @ to_cam < FACING_COS:
                continue
            L = np.linalg.norm(rel)
            hit, loc, *_ = sc.ray_cast(dg, Vector(C), Vector(rel / L), distance=L + 10 * eps)
            if hit and np.linalg.norm(np.array(loc) - p) <= max(10 * eps, 1e-4 * L):
                st['covered'] += 1
                break
        else:
            owner = str(owner)
            if owner not in missed[reg]:
                missed[reg][owner] = dict(object=owner, samples=0, example_mm=(p * units).round(2).tolist())
            missed[reg][owner]['samples'] += 1
    for region, st in stats.items():
        st['fraction'] = (st['covered'] / st['exposed']) if st['exposed'] else None
        st['uncovered_by_object'] = sorted(missed[region].values(), key=lambda row: -row['samples'])
    return stats


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--size-mm', type=float, default=None)
    ap.add_argument('--resolution', type=int, default=800)
    ap.add_argument('--lens', type=float, default=50.0)
    ap.add_argument('--poses-from', help='replay a saved closeups.json on the current geometry')
    ap.add_argument('--overlap', type=float, default=None)
    ap.add_argument('--objects')
    ap.add_argument('--regions', default=','.join(REGIONS))
    ap.add_argument('--skip-regions', default='')
    ap.add_argument('--min-coverage', type=float, default=0.95)
    ap.add_argument('--samples-surface', type=int, default=4000)
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--resume', action='store_true', help='skip tiles whose output PNG already exists at the right size')
    B.add_project_arg(ap)
    B.add_render_args(ap)
    B.add_style_args(ap)
    a = ap.parse(argv)
    regions = B.globs(a.regions)
    skip = B.globs(a.skip_regions)
    for r in regions + skip:
        if r not in REGIONS:
            raise BadInput('unknown region %r (regions: %s)' % (r, ', '.join(REGIONS)))
    if not regions:
        raise BadInput('no regions')
    size_mm = 600.0 if (a.size_mm is None and not a.poses_from) else a.size_mm
    overlap = 0.25 if (a.overlap is None and not a.poses_from) else a.overlap
    if (size_mm is not None and not (10 <= size_mm <= 100000)) or \
       (overlap is not None and not (0 <= overlap < 0.9)) or a.resolution < 8 or a.lens <= 0:
        raise BadInput('size, overlap, resolution or lens out of range')
    if a.samples_surface < 10:
        raise BadInput('--samples-surface must be at least 10')
    project = B.project_dir(a)
    mode = a.mode or 'lit'
    s, _, write_to = B.render_settings(a, os.path.join(project, 'data', 'render.json'))
    finishes = B.load_finishes(project)
    style, sky = B.resolve_style(a, finishes, project) if a.style else (None, None)
    hidden = B.hide_objects(B.globs(a.hide))
    geo = B.visible_geometry(B.globs(a.objects) or None)
    if not geo:
        raise BadInput('no geometry to look at')
    cov_geo = [ob for ob in geo if ob.get('rg_exterior', True)] or geo
    unit = B.mm_per_unit()
    lo, hi = B.bbox(geo)
    planned_regions = [r for r in REGIONS if r not in skip]
    if a.poses_from:
        views, dist, half, size_mm, overlap = replay_ring(a.poses_from, planned_regions, unit, size_mm, overlap, a.lens)
    else:
        views, dist, half = plan(lo, hi, size_mm / unit, overlap, a.lens, a.resolution, planned_regions, unit)
    far = float(np.linalg.norm(hi - lo)) * 4 + 10 * dist
    stats = coverage(cov_geo, views, half, regions, a.samples_surface, eps=0.5 / unit, far=far)
    ok = True
    for r in regions:
        st = stats[r]
        st['views'] = sum(1 for v in views if v['region'] == r)
        st['passed'] = st['fraction'] is not None and st['fraction'] >= a.min_coverage
        ok &= st['passed']
        print('COVER %-6s views %3d  exposed %5d  covered %5.1f%%  %s'
              % (r, st['views'], st['exposed'], 100 * (st['fraction'] or 0), 'pass' if st['passed'] else 'FAIL'))
    os.makedirs(a.out, exist_ok=True)
    look = None
    if not a.no_render:
        dev = B.setup_render(s)
        look = B.apply_style(style, sky, a.look, finishes, lo, hi) if style else \
            B.apply_mode(mode, a.look, finishes, lo, hi)
        s.update(dev)
    rows = []
    for v in views:
        f = None
        resumed = False
        if not a.no_render:
            f = os.path.join(os.path.abspath(a.out), v['name'] + '.png')
            if a.resume and B.valid_image(f, (a.resolution, a.resolution)):
                resumed = True
            else:
                cam = B.look_camera('rg close ' + v['name'], v['camera'], v['centre'], v['up'], a.lens,
                                    (a.resolution, a.resolution))
                cam.data.sensor_fit = 'HORIZONTAL'
                B.render_to(f)
        d = v['direction']
        rows.append(dict(name=v['name'], region=v['region'], centre_mm=(v['centre'] * unit).tolist(),
                         direction=d.tolist(), camera_mm=(v['camera'] * unit).tolist(), up=v['up'].tolist(),
                         lens_mm=a.lens, sensor_mm=36.0, resolution=[a.resolution, a.resolution],
                         distance_mm=dist * unit, file=f, resumed=resumed))
    if not a.no_render:
        B.write_settings(write_to, s, dev)
    res = dict(size_mm=size_mm, overlap=overlap, mode=mode, hidden=hidden, poses_from=a.poses_from,
               render=None if a.no_render else dict(s, look=look),
               regions=regions, skipped_regions=skip, min_coverage=a.min_coverage, coverage=stats, views=rows,
               passed=bool(ok))
    save_json(os.path.join(a.out, 'closeups.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
