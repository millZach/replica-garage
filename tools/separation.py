"""Check the parts that must come off: own objects, sensible pivots, no overlaps; render an exploded view. (Blender)

usage: blender -b <scene.blend> --python tools/separation.py -- --level 2|3 --out DIR
       (--parts "door_*,bonnet" | --parts-file parts.json) [--tolerance-mm 0.5] [--pivot-margin-mm 50]
       [--explode-mm 300] [--resolution 1200x750] [--no-render] [--mode clay] [render options as render_views.py]

--parts: names or globs; each object a glob matches is one part. --parts-file: {"2": [...], "3": [...]} and the
list for --level is used. For each part: it is its own object (the name matches exactly one geometry object, not
shared with another part), and its pivot (the object's origin) lies within its bounding box grown by
--pivot-margin-mm. For each pair of parts whose bounding boxes touch, the overlap is the deepest a part reaches
into the other: vertices inside a closed (watertight) part, measured to its surface, and for crossing surfaces the
depth of the crossing triangles behind each other. A finer mesh gives a closer value.
The exploded view moves each part out from the vehicle's centre by --explode-mm and renders it from the front
left, above (<out>/exploded.png). Nothing is saved back to the scene.
Writes <out>/separation.json. Exit 1 when a part is missing or not its own object, a pivot is off, or two parts
overlap by more than --tolerance-mm; 2 on bad input.
"""
import itertools
import math
import os
import sys

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/separation.py -- --level 2|3 --out DIR '
         '(--parts "door_*,bonnet" | --parts-file parts.json) [--tolerance-mm 0.5] [--no-render]')


def part_names(a):
    if a.parts and a.parts_file:
        raise BadInput('give --parts or --parts-file, not both')
    if a.parts_file:
        d = load_json(a.parts_file, 'parts file')
        d = d.get('levels', d) if isinstance(d, dict) else None
        lst = d.get(str(a.level)) if isinstance(d, dict) else None
        if not isinstance(lst, list):
            raise BadInput('parts file has no list for level %d' % a.level)
        return [str(x) for x in lst]
    names = B.globs(a.parts)
    if not names:
        raise BadInput('no parts given')
    return names


class Part:
    def __init__(self, ob):
        self.ob = ob
        self.md = B.MeshData(ob)
        self.lo, self.hi = self.md.verts.min(0), self.md.verts.max(0)
        self.closed = self.md.closed()
        self.bvh = BVHTree.FromPolygons([tuple(v) for v in self.md.verts], [tuple(t) for t in self.md.tris])
        self.n, _ = self.md.tri_normals()

    def inside(self, p, far):
        """Parity test along a fixed slanted direction (closed parts only)."""
        d = Vector((0.5773, 0.5774, 0.5775)).normalized()
        o = Vector(p)
        count, travelled = 0, 0.0
        while travelled < far:
            loc, nor, idx, dist = self.bvh.ray_cast(o, d, far - travelled)
            if loc is None:
                break
            count += 1
            o = loc + d * 1e-7
            travelled += dist + 1e-7
        return count % 2 == 1


def overlap_depth(A, Bp, far):
    depth = 0.0
    # crossing triangles: how far each triangle's corners lie behind the other's plane
    for ia, ib in A.bvh.overlap(Bp.bvh):
        ta, tb = A.md.verts[A.md.tris[ia]], Bp.md.verts[Bp.md.tris[ib]]
        na, nb = A.n[ia], Bp.n[ib]
        da = max(0.0, float(-((ta - tb[0]) @ nb).min()))       # corners of A behind B's face
        db = max(0.0, float(-((tb - ta[0]) @ na).min()))
        depth = max(depth, min(da, db))
    # whole vertices inside a closed part
    for X, Y in ((A, Bp), (Bp, A)):
        if not Y.closed:
            continue
        sel = np.all((X.md.verts >= Y.lo) & (X.md.verts <= Y.hi), axis=1)
        for p in X.md.verts[sel]:
            loc, nor, idx, dist = Y.bvh.find_nearest(Vector(p))
            if loc is not None and dist > depth and Y.inside(p, far):
                depth = dist
    return depth


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--level', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--parts')
    ap.add_argument('--parts-file')
    ap.add_argument('--tolerance-mm', type=float, default=0.5)
    ap.add_argument('--pivot-margin-mm', type=float, default=50.0)
    ap.add_argument('--explode-mm', type=float, default=300.0)
    ap.add_argument('--resolution', default='1200x750')
    ap.add_argument('--no-render', action='store_true')
    B.add_render_args(ap)
    a = ap.parse(argv)
    if a.level not in (2, 3):
        raise BadInput('--level must be 2 or 3')
    try:
        rw, rh = [int(v) for v in a.resolution.lower().split('x')]
    except ValueError:
        raise BadInput('--resolution must look like 1200x750')
    names = part_names(a)
    s, _ = B.render_settings(a)
    finishes = B.load_finishes(a.finishes)
    u = B.mm_per_unit()
    rows, parts, ok = [], [], True
    claimed = {}
    for nm in names:
        obs = [o for o in B.find_objects(nm) if o.type in B.GEOMETRY]
        if not obs:
            rows.append(dict(name=nm, own_object=False, pivot_ok=False, note='no object matches'))
            ok = False
            continue
        for ob in obs:
            if ob.name in claimed:
                continue
            claimed[ob.name] = nm
            p = Part(ob)
            shared = [o.name for o in B.bpy.context.scene.objects
                      if o is not ob and o.type == ob.type and o.data is ob.data and o.name in claimed]
            own = len(p.md.tris) > 0 and not shared
            piv = np.array(ob.matrix_world.translation)
            m = a.pivot_margin_mm / u
            pivot_ok = bool(np.all(piv >= p.lo - m) and np.all(piv <= p.hi + m))
            rows.append(dict(name=ob.name, pattern=nm, own_object=bool(own), pivot_ok=pivot_ok,
                             pivot_mm=(piv * u).tolist(), bbox_min_mm=(p.lo * u).tolist(),
                             bbox_max_mm=(p.hi * u).tolist(), closed=p.closed, shares_mesh_with=shared))
            ok &= own and pivot_ok
            parts.append(p)
    tol = a.tolerance_mm / u
    allv = np.concatenate([p.md.verts for p in parts]) if parts else np.zeros((1, 3))
    far = float(np.linalg.norm(allv.max(0) - allv.min(0))) * 2 + 1.0
    overlaps = []
    for A, C in itertools.combinations(parts, 2):
        if np.any(A.lo > C.hi + tol) or np.any(C.lo > A.hi + tol):
            continue
        d = overlap_depth(A, C, far) * u
        passed = d <= a.tolerance_mm
        ok &= passed
        overlaps.append(dict(a=A.ob.name, b=C.ob.name, depth_mm=d, passed=passed))
        print('PAIR %-20s %-20s overlap %.2f mm  %s' % (A.ob.name, C.ob.name, d, 'pass' if passed else 'FAIL'))
    for r in rows:
        print('PART %-24s own %s  pivot %s' % (r['name'], r['own_object'], r['pivot_ok']))
    os.makedirs(a.out, exist_ok=True)
    exploded = None
    if not a.no_render and parts:
        B.hide_objects(B.globs(a.hide))
        geo = B.visible_geometry()
        lo, hi = B.bbox(geo)
        centre = (lo + hi) / 2
        for p in parts:
            c = (p.lo + p.hi) / 2
            d = c - centre
            d = d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-9 else np.array([0, 0, 1.0])
            p.ob.matrix_world.translation += Vector(d * a.explode_mm / u)
        B.bpy.context.view_layer.update()
        lo, hi = B.bbox(geo)
        centre = (lo + hi) / 2
        rad = float(np.linalg.norm(hi - lo)) / 2
        view = np.array([-0.62, -0.62, 0.48])
        view /= np.linalg.norm(view)
        dist = rad / math.tan(math.atan(18.0 / 35.0)) * 1.1
        dev = B.setup_render(s)
        look = B.apply_mode(s['mode'], s['finish'], finishes)
        s.update(dev, look=look)
        B.look_camera('rg exploded', centre + view * dist, centre, (0, 0, 1), 35.0, (rw, rh))
        exploded = os.path.join(os.path.abspath(a.out), 'exploded.png')
        B.render_to(exploded)
    res = dict(level=a.level, tolerance_mm=a.tolerance_mm, pivot_margin_mm=a.pivot_margin_mm, parts=rows,
               overlaps=overlaps, explode_mm=a.explode_mm, exploded=exploded,
               render=None if exploded is None else s, passed=bool(ok))
    save_json(os.path.join(a.out, 'separation.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
