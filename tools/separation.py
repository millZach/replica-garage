"""Check the parts that come off: own objects, pivots where parts.json puts them, no overlaps; exploded view. (Blender)

usage: blender -b <scene.blend> --python tools/separation.py -- --level 2|3 --out DIR [--project DIR]
       [--parts FILE] [--tolerance-mm 0.5] [--pivot-tolerance-mm 1] [--explode-mm 300] [--resolution 1200x750]
       [--no-render] [--mode clay|lit|zebra] [--look NAME] [--device CPU|GPU] [--samples N]

parts.json (default <project>/data/parts.json) is a list of {"part", "fixed_to", "pivot": [x, y, z] mm,
"level": 2 | 3, "basis"}; --level 2 checks the level 2 parts, --level 3 all of them. For each part: it is its own
object (exactly one geometry object registered under that part name, with separable=True), and its origin
is within --pivot-tolerance-mm of the pivot in parts.json. For each pair of parts whose bounding boxes touch, the
overlap is the deepest one reaches into the other: vertices inside a closed (watertight) part, measured to its
surface, and for crossing surfaces the depth of the crossing triangles behind each other (a finer mesh gives a
closer value).
The exploded view moves each part away from the part it is fixed to (or from the vehicle's centre) by
--explode-mm and renders it from the front left, above, to <out>/exploded.png. Nothing is saved to the scene.
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
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, number, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/separation.py -- --level 2|3 --out DIR [--project DIR] '
         '[--parts FILE] [--tolerance-mm 0.5] [--no-render]')


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
        o, count, travelled = Vector(p), 0, 0.0
        while travelled < far:
            loc, nor, idx, dist = self.bvh.ray_cast(o, d, far - travelled)
            if loc is None:
                break
            count += 1
            o = loc + d * 1e-7
            travelled += dist + 1e-7
        return count % 2 == 1


def overlap_depth(A, C, far):
    depth = 0.0
    for ia, ic in A.bvh.overlap(C.bvh):                 # crossing triangles
        ta, tc = A.md.verts[A.md.tris[ia]], C.md.verts[C.md.tris[ic]]
        da = max(0.0, float(-((ta - tc[0]) @ C.n[ic]).min()))       # corners of A behind C's face
        dc = max(0.0, float(-((tc - ta[0]) @ A.n[ia]).min()))
        depth = max(depth, min(da, dc))
    for X, Y in ((A, C), (C, A)):                       # whole vertices inside a closed part
        if not Y.closed:
            continue
        sel = np.all((X.md.verts >= Y.lo) & (X.md.verts <= Y.hi), axis=1)
        for p in X.md.verts[sel]:
            loc, nor, idx, dist = Y.bvh.find_nearest(Vector(p))
            if loc is not None and dist > depth and Y.inside(p, far):
                depth = dist
    return depth


def read_parts(path, level):
    d = F.parts(load_json(path, 'parts.json'))
    if not d:
        raise BadInput('parts.json must be a non-empty list of parts')
    out = []
    for i, p in enumerate(d):
        if not isinstance(p, dict) or 'part' not in p or 'level' not in p:
            raise BadInput('parts.json entry %d needs "part" and "level"' % (i + 1))
        lv = int(number(p['level'], 'level'))
        if lv not in (2, 3):
            raise BadInput('part %r: level must be 2 or 3' % p['part'])
        piv = p.get('pivot')
        if piv is not None and not (isinstance(piv, list) and len(piv) == 3):
            raise BadInput('part %r: pivot must be [x, y, z] in mm' % p['part'])
        if lv <= level:
            out.append(dict(p, level=lv))
    if not out:
        raise BadInput('parts.json has no parts at level %d or below' % level)
    return out


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--level', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--parts')
    ap.add_argument('--tolerance-mm', type=float, default=0.5)
    ap.add_argument('--pivot-tolerance-mm', type=float, default=1.0)
    ap.add_argument('--explode-mm', type=float, default=300.0)
    ap.add_argument('--resolution', default='1200x750')
    ap.add_argument('--no-render', action='store_true')
    B.add_project_arg(ap)
    B.add_render_args(ap)
    a = ap.parse(argv)
    if a.level not in (2, 3):
        raise BadInput('--level must be 2 or 3')
    try:
        rw, rh = [int(v) for v in a.resolution.lower().split('x')]
    except ValueError:
        raise BadInput('--resolution must look like 1200x750')
    project = B.project_dir(a)
    listed = read_parts(a.parts or os.path.join(project, 'data', 'parts.json'), a.level)
    u = B.mm_per_unit()
    rows, parts, ok = [], [], True
    for e in listed:
        obs = B.part_objects(str(e['part']))
        row = dict(part=e['part'], level=e['level'], fixed_to=e.get('fixed_to'), basis=e.get('basis'),
                   objects=[o.name for o in obs])
        if len(obs) != 1:
            row.update(own_object=False, pivot_ok=False,
                       note='no object' if not obs else '%d objects share this part name' % len(obs))
            ok = False
            rows.append(row)
            continue
        p = Part(obs[0])
        piv = np.array(obs[0].matrix_world.translation) * u
        if e.get('pivot') is not None:
            want = np.array([number(c, 'pivot') for c in e['pivot']])
            off = float(np.linalg.norm(piv - want))
            pivot_ok = off <= a.pivot_tolerance_mm
            row.update(pivot_wanted_mm=want.tolist(), pivot_off_mm=off)
        else:
            pivot_ok = False
            row['note'] = 'parts.json gives no pivot'
        sep = bool(obs[0].get('rg_separable', False))
        own = len(p.md.tris) > 0 and sep and not any(o is not obs[0] and o.data is obs[0].data
                                                     for o in B.bpy.context.scene.objects if o.type == obs[0].type)
        if not sep:
            row['note'] = 'not registered as separable (ctx.add(..., separable=True))'
        row.update(own_object=bool(own), pivot_ok=bool(pivot_ok), pivot_mm=piv.tolist(), closed=p.closed,
                   separable_flag=bool(obs[0].get('rg_separable', False)), bbox_min_mm=(p.lo * u).tolist(),
                   bbox_max_mm=(p.hi * u).tolist())
        ok &= own and pivot_ok
        rows.append(row)
        parts.append((e, p))
    tol = a.tolerance_mm / u
    allv = np.concatenate([p.md.verts for _, p in parts]) if parts else np.zeros((1, 3))
    far = float(np.linalg.norm(allv.max(0) - allv.min(0))) * 2 + 1.0
    overlaps = []
    for (ea, A), (ec, C) in itertools.combinations(parts, 2):
        if np.any(A.lo > C.hi + tol) or np.any(C.lo > A.hi + tol):
            continue
        d = overlap_depth(A, C, far) * u
        passed = d <= a.tolerance_mm
        ok &= passed
        overlaps.append(dict(a=ea['part'], b=ec['part'], depth_mm=d, passed=passed))
        print('PAIR %-20s %-20s overlap %.2f mm  %s' % (ea['part'], ec['part'], d, 'pass' if passed else 'FAIL'))
    for r in rows:
        print('PART %-24s own %s  pivot %s%s' % (r['part'], r['own_object'], r['pivot_ok'],
                                                ('  (' + r['note'] + ')') if r.get('note') else ''))
    os.makedirs(a.out, exist_ok=True)
    exploded, look = None, None
    if not a.no_render and parts:
        s, _, write_to = B.render_settings(a, os.path.join(project, 'data', 'render.json'))
        finishes = B.load_finishes(project)
        B.hide_objects(B.globs(a.hide))
        geo = B.visible_geometry()
        lo, hi = B.bbox(geo)
        centre = (lo + hi) / 2
        for e, p in parts:
            base = B.part_objects(str(e.get('fixed_to'))) if e.get('fixed_to') else []
            ref = np.mean(B.bbox(base), axis=0) if base else centre
            d = (p.lo + p.hi) / 2 - ref
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
        look = B.apply_mode(a.mode or 'clay', a.look, finishes, lo, hi)
        B.look_camera('rg exploded', centre + view * dist, centre, (0, 0, 1), 35.0, (rw, rh))
        exploded = os.path.join(os.path.abspath(a.out), 'exploded.png')
        B.render_to(exploded)
        B.write_settings(write_to, s, dev)
    res = dict(level=a.level, tolerance_mm=a.tolerance_mm, pivot_tolerance_mm=a.pivot_tolerance_mm, parts=rows,
               overlaps=overlaps, explode_mm=a.explode_mm, exploded=exploded, look=look, passed=bool(ok))
    save_json(os.path.join(a.out, 'separation.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
