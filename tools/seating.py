"""Measure how parts sit on their panels: the signed step all round each part's edge.  (runs in Blender)

usage: blender -b <scene.blend> --python tools/seating.py -- --out DIR [--project DIR] [--build FILE]
       [--part NAME --on PANEL] [--points 72] [--max-step-mm 3] [--edge-group GROUP] [--all-loops]

Seats come from build.json (default <project>/data/build.json): every {"part", "on"} in every assembly's "seats".
--part <name> --on <panel> measures one part instead (a builder on its own trial assembly). Names are the ones
the builders registered (ctx.add part=...), or object names. A part's edge is its open border (edges with one
face), the longest loop unless --all-loops; a part with no open border needs --edge-group, a vertex group naming
its edge. --points points are spaced evenly along the edge; at each, the nearest point on the panel is found and
the step is the distance along the panel's normal there: + when the part stands proud, - when it is sunk (panel
normals point outward). The gap across the panel's surface is reported too.
Writes <out>/seating.json. Exit 1 when any step is more than --max-step-mm either way, or a part or panel listed
in build.json is not in the scene; 2 on bad input.
"""
import os
import sys

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/seating.py -- --out DIR [--project DIR] [--build FILE] '
         '[--part NAME --on PANEL] [--max-step-mm 3]')


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
        for _, ei in adj[start]:
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
        return P[:1]
    t = np.linspace(0, s[-1], n, endpoint=not closed)
    return np.stack([np.interp(t, s, P[:, i]) for i in range(3)], 1)


def edge_points(objs, n_points, group, all_loops):
    chains = []
    source = group or 'open_border'
    effective_group = group
    if not effective_group:
        if any('rg_seat' in ob.vertex_groups for ob in objs):
            effective_group = 'rg_seat'
            source = 'rg_seat'
    for ob in objs:
        md = B.MeshData(ob, layers=bool(effective_group))
        if effective_group:
            g = getattr(md, 'vgroups', {}).get(effective_group)
            if not g:
                continue
            edges = [tuple(e) for e in md.edges if e[0] in g and e[1] in g]
        else:
            edges = [tuple(e) for e, n in zip(md.edges, md.edge_faces) if n == 1]
        for c, cl in loops(edges):
            P = md.verts[c + ([c[0]] if cl else [])]
            chains.append((md.verts[c], cl, float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())))
    if not chains:
        return None, source
    use = chains if all_loops else [max(chains, key=lambda c: c[2])]
    total = sum(c[2] for c in use)
    pts = np.concatenate([resample(P, cl, max(4, int(round(n_points * L / total))) if total > 0 else n_points)
                          for P, cl, L in use])
    return pts, source


def panel_tree(objs):
    verts, tris = [], []
    for ob in objs:
        md = B.MeshData(ob)
        tris += [tuple(int(i) + len(verts) for i in t) for t in md.tris]
        verts += [tuple(v) for v in md.verts]
    return BVHTree.FromPolygons(verts, tris) if tris else None


def seat(part, on, a, u):
    row = dict(part=part, on=on)
    pobs, nobs = B.part_objects(part), B.part_objects(on)
    if not pobs or not nobs:
        row.update(max_abs_step_mm=None, passed=False,
                   note='%s is not in the scene' % (('part %r' % part) if not pobs else ('panel %r' % on)))
        return row
    pts, source = edge_points(pobs, a.points, a.edge_group, a.all_loops)
    row['edge_source'] = source
    if pts is None:
        row.update(max_abs_step_mm=None, passed=False,
                   note='part %r has no open edge; mark it with ctx.seat_edge (rg_seat) or --edge-group' % part)
        return row
    bvh = panel_tree(nobs)
    if bvh is None:
        row.update(max_abs_step_mm=None, passed=False, note='panel %r has no faces' % on)
        return row
    pts_out = []
    for p in pts:
        loc, nor, idx, dist = bvh.find_nearest(Vector(p))
        n = np.array(nor)
        d = p - np.array(loc)
        step = float(d @ n)
        pts_out.append(dict(position_mm=(p * u).tolist(), panel_point_mm=(np.array(loc) * u).tolist(),
                            step_mm=step * u, gap_mm=float(np.linalg.norm(d - step * n)) * u))
    steps = np.array([r['step_mm'] for r in pts_out])
    worst = float(np.abs(steps).max())
    row.update(points=pts_out, max_abs_step_mm=worst, min_step_mm=float(steps.min()), max_step_mm=float(steps.max()),
               mean_step_mm=float(steps.mean()), max_gap_mm=float(max(r['gap_mm'] for r in pts_out)),
               passed=worst <= a.max_step_mm)
    return row


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--build')
    ap.add_argument('--part')
    ap.add_argument('--on')
    ap.add_argument('--points', type=int, default=72)
    ap.add_argument('--max-step-mm', type=float, default=3.0)
    ap.add_argument('--edge-group')
    ap.add_argument('--all-loops', action='store_true')
    B.add_project_arg(ap)
    a = ap.parse(argv)
    if a.points < 4:
        raise BadInput('--points must be at least 4')
    if bool(a.part) != bool(a.on):
        raise BadInput('--part and --on go together')
    if a.part:
        if not B.part_objects(a.part):
            raise BadInput('part %r is not in the scene' % a.part)
        if not B.part_objects(a.on):
            raise BadInput('panel %r is not in the scene' % a.on)
        pairs = [(a.part, a.on)]
    else:
        build = F.build(load_json(a.build or os.path.join(B.project_dir(a), 'data', 'build.json'), 'build list'))
        pairs = []
        for e in build:
            for st in e['seats']:
                pairs.append((str(st['part']), str(st['on'])))
    u = B.mm_per_unit()
    rows = [seat(p, o, a, u) for p, o in pairs]
    for r in rows:
        print('SEAT %-24s on %-20s %s  %s' % (r['part'], r['on'], r.get('note') or 'step %+.2f to %+.2f mm' % (
            r['min_step_mm'], r['max_step_mm']), 'pass' if r['passed'] else 'FAIL'))
    steps = [r['max_abs_step_mm'] for r in rows if r['max_abs_step_mm'] is not None]
    ok = all(r['passed'] for r in rows)
    res = dict(seats=rows, max_abs_step_mm=max(steps) if steps else None, limit_mm=a.max_step_mm,
               sign='+ part proud of the panel, - part sunk', passed=bool(ok))
    save_json(os.path.join(a.out, 'seating.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
