"""Measure how parts sit on their panels and how adjacent body/glass panels meet at seams. (Blender)

usage: blender -b <scene.blend> --python tools/seating.py -- --out DIR [--project DIR] [--build FILE]
       [--seams FILE] [--part NAME --on PANEL] [--seam-pair A:B] [--points 72] [--max-step-mm 3]
       [--min-gap-mm 1.5] [--max-gap-mm 5.0] [--max-flush-mm 2.0] [--search-radius-mm 40]
       [--edge-group GROUP] [--all-loops]

Checks two kinds of joints:
  1. Accessory / insert seats from build.json (every {"part", "on"} in every assembly's "seats"), or
     --part <name> --on <panel>. At --points evenly spaced points along the part's open border (or
     vertex group rg_seat / --edge-group), measures the signed step along the panel's normal (+ proud,
     - sunk) within --max-step-mm (default 3 mm).
  2. Body-to-body & glass-to-body panel seams from data/seams.json (--seams FILE), build.json
     ("seams" lists), or --seam-pair A:B (e.g. hood:bumper, hatch_glass:hatch, quarter:rear_bumper).
     Measures each declared pair via seams.py: gap must stay in [--min-gap-mm, --max-gap-mm] (default
     1.5 to 5.0 mm) and flush step within --max-flush-mm (default 2.0 mm).

Writes <out>/seating.json (with both "seats" and "seams"). Exit 1 when any seat or seam fails, or a
declared part/panel is missing from the scene; 2 on bad input.
"""
import os
import sys

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import _formats as F  # noqa: E402
import seams as S  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/seating.py -- --out DIR [--project DIR] [--build FILE] '
         '[--seams FILE] [--part NAME --on PANEL] [--seam-pair A:B] [--max-step-mm 3]')


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
    ap.add_argument('--seams')
    ap.add_argument('--part')
    ap.add_argument('--on')
    ap.add_argument('--seam-pair', action='append', default=[])
    ap.add_argument('--points', type=int, default=72)
    ap.add_argument('--max-step-mm', type=float, default=3.0)
    ap.add_argument('--min-gap-mm', type=float, default=S.DEFAULT_MIN_GAP_MM)
    ap.add_argument('--max-gap-mm', type=float, default=S.DEFAULT_MAX_GAP_MM)
    ap.add_argument('--max-flush-mm', type=float, default=S.DEFAULT_MAX_FLUSH_MM)
    ap.add_argument('--search-radius-mm', type=float, default=S.DEFAULT_SEARCH_RADIUS_MM)
    ap.add_argument('--edge-group')
    ap.add_argument('--all-loops', action='store_true')
    B.add_project_arg(ap)
    a = ap.parse(argv)
    if a.points < 4:
        raise BadInput('--points must be at least 4')
    if bool(a.part) != bool(a.on):
        raise BadInput('--part and --on go together')
    if a.min_gap_mm < 0 or a.max_gap_mm <= a.min_gap_mm or a.max_flush_mm <= 0 or a.search_radius_mm <= 0:
        raise BadInput('invalid seam gap/flush/search-radius limits')

    project = B.project_dir(a)
    pairs = []
    seam_pairs = []
    if a.part:
        if not B.part_objects(a.part):
            raise BadInput('part %r is not in the scene' % a.part)
        if not B.part_objects(a.on):
            raise BadInput('panel %r is not in the scene' % a.on)
        pairs = [(a.part, a.on)]
    if a.seam_pair:
        seam_pairs = S.load_seam_pairs(
            project, cli_pairs=a.seam_pair,
            default_min_gap=a.min_gap_mm, default_max_gap=a.max_gap_mm,
            default_max_flush=a.max_flush_mm, default_search_radius=a.search_radius_mm,
        )
    if not a.part and not a.seam_pair:
        build_path = a.build or os.path.join(project, 'data', 'build.json')
        if os.path.isfile(build_path) or a.build or not a.seams:
            build = F.build(load_json(build_path, 'build list'))
            for e in build:
                for st in e['seats']:
                    pairs.append((str(st['part']), str(st['on'])))
        seam_pairs = S.load_seam_pairs(
            project, seams_file=a.seams, build_file=a.build,
            default_min_gap=a.min_gap_mm, default_max_gap=a.max_gap_mm,
            default_max_flush=a.max_flush_mm, default_search_radius=a.search_radius_mm,
        )
    elif a.seams:
        seam_pairs.extend(S.load_seam_pairs(
            project, seams_file=a.seams, build_file=None,
            default_min_gap=a.min_gap_mm, default_max_gap=a.max_gap_mm,
            default_max_flush=a.max_flush_mm, default_search_radius=a.search_radius_mm,
        ))

    u = B.mm_per_unit()
    rows = [seat(p, o, a, u) for p, o in pairs]
    for r in rows:
        print('SEAT %-24s on %-20s %s  %s' % (r['part'], r['on'], r.get('note') or 'step %+.2f to %+.2f mm' % (
            r['min_step_mm'], r['max_step_mm']), 'pass' if r['passed'] else 'FAIL'))
    seam_rows = S.evaluate_pairs(seam_pairs, n_points=a.points) if seam_pairs else []
    steps = [r['max_abs_step_mm'] for r in rows if r['max_abs_step_mm'] is not None]
    ok = all(r['passed'] for r in rows) and all(r['passed'] for r in seam_rows)
    res = dict(seats=rows, seams=seam_rows, max_abs_step_mm=max(steps) if steps else None, limit_mm=a.max_step_mm,
               seam_limits=dict(min_gap_mm=a.min_gap_mm, max_gap_mm=a.max_gap_mm, max_flush_mm=a.max_flush_mm),
               sign='+ part proud of the panel, - part sunk', passed=bool(ok))
    save_json(os.path.join(a.out, 'seating.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
