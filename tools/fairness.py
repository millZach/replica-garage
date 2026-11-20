"""Measure how fair each painted panel is: the angle between neighbouring faces, away from real creases. (Blender)

usage: blender -b <scene.blend> --python tools/fairness.py -- --out DIR [--project DIR] [--crease-margin-mm 10]
       [--max-p99-deg 2.5] [--max-deg 5] [--base-mesh]

The panels are the objects the kit registered as painted skin (ctx.add(..., panel=True)); the creases are the
edges marked with ctx.crease (the rg_crease edge attribute). Every edge within --crease-margin-mm of a crease is
left out, so the fold and the faces rolling into it are not counted. For every edge shared by exactly two faces
the angle between the two face normals is taken; per panel the 99th percentile and the maximum are reported, with
where the maximum is (mm). The evaluated mesh (as it renders) is measured; --base-mesh measures the mesh as
modelled, for when a modifier drops the crease marks.
Writes <out>/fairness.json. Exit 1 when any panel is over either limit, 2 on bad input (no registered panels).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/fairness.py -- --out DIR [--project DIR] '
         '[--crease-margin-mm 10] [--max-p99-deg 2.5] [--max-deg 5] [--base-mesh]')


class BaseMesh(B.MeshData):
    """MeshData of the mesh as modelled (no modifiers)."""

    def __init__(self, ob):
        dg = B.depsgraph()
        saved = [(m, m.show_render, m.show_viewport) for m in ob.modifiers]
        for m, _, _ in saved:
            m.show_viewport = m.show_render = False
        dg.update()
        try:
            super().__init__(ob, B.depsgraph(), layers=True)
        finally:
            for m, r, v in saved:
                m.show_render, m.show_viewport = r, v


def crease_mask(md, names):
    """Boolean per edge: in one of the named creases. Also returns which names were found."""
    mask = np.zeros(len(md.edges), bool)
    found = []
    for nm in names:
        if nm == 'sharp' and 'sharp_edge' in md.attributes:
            mask |= md.attributes['sharp_edge']
            found.append(nm)
        elif nm in md.attributes:
            mask |= md.attributes[nm]
            found.append(nm)
        elif nm in getattr(md, 'vgroups', {}):
            g = md.vgroups[nm]
            mask |= np.array([a in g and b in g for a, b in md.edges], bool)
            found.append(nm)
    return mask, found


def near(points, segs_a, segs_b, radius):
    """Boolean per point: within radius of any segment (all in the same units)."""
    from mathutils import kdtree
    if not len(segs_a):
        return np.zeros(len(points), bool)
    step = radius / 3.0
    samples = []
    for a, b in zip(segs_a, segs_b):
        n = max(2, int(np.ceil(np.linalg.norm(b - a) / step)) + 1)
        samples.append(a + (b - a) * np.linspace(0, 1, n)[:, None])
    S = np.concatenate(samples)
    kd = kdtree.KDTree(len(S))
    for i, p in enumerate(S):
        kd.insert(p, i)
    kd.balance()
    reach = radius + step / 2
    return np.array([kd.find(p)[2] <= reach for p in points], bool)


def measure(md, creases, margin):
    nrm, area = md.tri_normals()
    # face normal per polygon: area-weighted mean of its triangles
    npoly = len(md.poly_loop_total)
    pn = np.zeros((npoly, 3))
    np.add.at(pn, md.tri_poly, nrm * area[:, None])
    pl = np.linalg.norm(pn, axis=1)
    good_poly = pl > 1e-18
    pn[good_poly] /= pl[good_poly, None]
    poly_of_loop = np.repeat(np.arange(npoly), md.poly_loop_total)
    order = np.argsort(md.loop_edge, kind='stable')
    e_sorted = md.loop_edge[order]
    p_sorted = poly_of_loop[order]
    inner = np.flatnonzero(md.edge_faces == 2)
    start = np.searchsorted(e_sorted, inner)
    pa, pb = p_sorted[start], p_sorted[start + 1]
    ok = good_poly[pa] & good_poly[pb]
    inner, pa, pb = inner[ok], pa[ok], pb[ok]
    cosang = np.clip((pn[pa] * pn[pb]).sum(1), -1.0, 1.0)
    ang = np.degrees(np.arccos(cosang))
    mid = md.verts[md.edges[inner]].mean(1)
    if creases.any():
        ce = md.edges[creases]
        drop = creases[inner] | near(mid, md.verts[ce[:, 0]], md.verts[ce[:, 1]], margin)
        ang, mid = ang[~drop], mid[~drop]
    return ang, mid, int(creases.sum())


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--crease-margin-mm', type=float, default=10.0)
    ap.add_argument('--max-p99-deg', type=float, default=2.5)
    ap.add_argument('--max-deg', type=float, default=5.0)
    ap.add_argument('--base-mesh', action='store_true')
    B.add_project_arg(ap)
    a = ap.parse(argv)
    if a.crease_margin_mm < 0:
        raise BadInput('--crease-margin-mm must be >= 0')
    panels = B.registered('rg_panel')
    if not panels:
        raise BadInput('no panels: the scene has no object registered with ctx.add(..., panel=True)')
    names = ['rg_crease']
    unit = B.mm_per_unit()
    margin = a.crease_margin_mm / unit
    rows, ok, found_any = {}, True, set()
    for ob in panels:
        md = BaseMesh(ob) if a.base_mesh else B.MeshData(ob, layers=True)
        cm, found = crease_mask(md, names)
        found_any |= set(found)
        ang, mid, ncrease = measure(md, cm, margin)
        if len(ang):
            i = int(np.argmax(ang))
            r = dict(p99_deg=float(np.percentile(ang, 99)), max_deg=float(ang[i]),
                     max_at_mm=(mid[i] * unit).tolist(), mean_deg=float(ang.mean()), edges=int(len(ang)))
            r['passed'] = r['p99_deg'] <= a.max_p99_deg and r['max_deg'] <= a.max_deg
        else:
            r = dict(p99_deg=None, max_deg=None, edges=0, passed=False, note='no edges left to measure')
        r.update(crease_edges=ncrease, creases_found=found)
        ok &= r['passed']
        r['part'] = ob.get('rg_part', ob.name)
        rows[ob.name] = r
        print('PANEL %-24s edges %6d  p99 %6s  max %6s  %s' % (
            ob.name, r['edges'], '-' if r['p99_deg'] is None else '%.2f' % r['p99_deg'],
            '-' if r['max_deg'] is None else '%.2f' % r['max_deg'], 'pass' if r['passed'] else 'FAIL'))
    res = dict(max_p99_deg=a.max_p99_deg, max_deg=a.max_deg, crease_margin_mm=a.crease_margin_mm, creases=names,

               mesh='base' if a.base_mesh else 'evaluated', panels=rows, passed=bool(ok))
    save_json(os.path.join(a.out, 'fairness.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
