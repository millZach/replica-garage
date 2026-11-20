"""Measure how a part sits in its panel: the signed step all round the part's edge.        (runs in Blender)

usage: blender -b <scene.blend> --python tools/seating.py -- --part NAME --panel NAME --out DIR
       [--points 72] [--max-step-mm 3] [--edge-group GROUP] [--all-loops] [--name seating]

The part's edge is its open border (edges with one face); the longest border loop is used unless --all-loops.
A part with no open border needs --edge-group, a vertex group naming the edge's vertices. --points points are
spaced evenly along the edge. At each, the nearest point on the panel is found; the step is the distance along
the panel's normal there, + when the part stands proud of the panel, - when it is sunk (the panel's normals must
point outward). The gap across the panel's surface is reported too.
Writes <out>/<name>.json (default seating.json; gates.py reads seating*.json). Exit 1 when the step anywhere is
more than --max-step-mm either way, 2 on bad input.
"""
import os
import sys

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/seating.py -- --part NAME --panel NAME --out DIR '
         '[--points 72] [--max-step-mm 3] [--edge-group GROUP]')


def one(name, what):
    sc = B.bpy.context.scene
    ob = sc.objects.get(name)
    if ob is None or ob.type not in B.GEOMETRY:
        raise BadInput('%s %r is not an object with geometry in the scene' % (what, name))
    return ob


def loops(edges):
    """Chains of connected edges: list of (vertex index list, closed)."""
    adj = {}
    for i, (a, b) in enumerate(edges):
        adj.setdefault(a, []).append((b, i))
        adj.setdefault(b, []).append((a, i))
    used = np.zeros(len(edges), bool)
    out = []
    ends = [v for v, n in adj.items() if len(n) == 1]
    for start in ends + list(adj):
        for nb, ei in adj[start]:
            if used[ei]:
                continue
            chain, cur = [start], start
            while True:
                nxt = [(v, e) for v, e in adj[cur] if not used[e]]
                if not nxt:
                    break
                v, e = nxt[0]
                used[e] = True
                chain.append(v)
                cur = v
                if v == start:
                    break
            closed = len(chain) > 2 and chain[-1] == chain[0]
            out.append((chain[:-1] if closed else chain, closed))
    return out


def resample(P, closed, n):
    if closed:
        P = np.vstack([P, P[:1]])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] <= 0:
        return P[:1], 0.0
    t = np.linspace(0, s[-1], n, endpoint=not closed)
    return np.stack([np.interp(t, s, P[:, i]) for i in range(3)], 1), float(s[-1])


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--part', required=True)
    ap.add_argument('--panel', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--points', type=int, default=72)
    ap.add_argument('--max-step-mm', type=float, default=3.0)
    ap.add_argument('--edge-group')
    ap.add_argument('--all-loops', action='store_true')
    ap.add_argument('--name', default='seating')
    a = ap.parse(argv)
    if a.points < 4:
        raise BadInput('--points must be at least 4')
    part, panel = one(a.part, 'part'), one(a.panel, 'panel')
    if part == panel:
        raise BadInput('part and panel are the same object')
    md = B.MeshData(part, layers=bool(a.edge_group))
    if a.edge_group:
        g = getattr(md, 'vgroups', {}).get(a.edge_group)
        if not g:
            raise BadInput('part %r has no vertex group %r' % (a.part, a.edge_group))
        edges = [tuple(e) for e in md.edges if e[0] in g and e[1] in g]
    else:
        edges = [tuple(e) for e, n in zip(md.edges, md.edge_faces) if n == 1]
    if not edges:
        raise BadInput('part %r has no open edge; name its edge with --edge-group' % a.part)
    chains = loops(edges)
    lens = [np.linalg.norm(np.diff(md.verts[c + ([c[0]] if cl else [])], axis=0), axis=1).sum() for c, cl in chains]
    use = list(range(len(chains))) if a.all_loops else [int(np.argmax(lens))]
    total = sum(lens[i] for i in use)
    pts = []
    for i in use:
        c, cl = chains[i]
        n = max(4, int(round(a.points * lens[i] / total))) if total > 0 else a.points
        p, _ = resample(md.verts[c], cl, n)
        pts.append(p)
    pts = np.concatenate(pts)
    pm = B.MeshData(panel)
    if not len(pm.tris):
        raise BadInput('panel %r has no faces' % a.panel)
    bvh = BVHTree.FromPolygons([tuple(v) for v in pm.verts], [tuple(t) for t in pm.tris])
    u = B.mm_per_unit()
    rows = []
    for p in pts:
        loc, nor, idx, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            raise BadInput('panel %r has no surface near the part' % a.panel)
        n = np.array(nor)
        d = p - np.array(loc)
        step = float(d @ n)
        gap = float(np.linalg.norm(d - step * n))
        rows.append(dict(position_mm=(p * u).tolist(), panel_point_mm=(np.array(loc) * u).tolist(),
                         step_mm=step * u, gap_mm=gap * u))
    steps = np.array([r['step_mm'] for r in rows])
    worst = float(np.abs(steps).max())
    ok = worst <= a.max_step_mm
    res = dict(part=a.part, panel=a.panel, points=rows, max_abs_step_mm=worst, min_step_mm=float(steps.min()),
               max_step_mm=float(steps.max()), mean_step_mm=float(steps.mean()),
               max_gap_mm=float(max(r['gap_mm'] for r in rows)), edge_loops=len(chains), loops_used=len(use),
               limit_mm=a.max_step_mm, sign='+ part proud of the panel, - part sunk', passed=bool(ok))
    save_json(os.path.join(a.out, a.name + '.json'), res)
    print('SEATING %s on %s: step %+.2f to %+.2f mm (worst %.2f)  %s'
          % (a.part, a.panel, steps.min(), steps.max(), worst, 'pass' if ok else 'FAIL'))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
