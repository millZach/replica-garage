"""Measure how fair each painted panel is: adjacent face angles and multi-scale waviness, away from creases. (Blender)

usage: blender -b <scene.blend> --python tools/fairness.py -- --out DIR [--project DIR] [--crease-margin-mm 10]
       [--max-p99-deg 2.5] [--max-deg 5] [--wave-radius-mm 60] [--max-wave-mm 1.0] [--base-mesh]

The panels are the objects the kit registered as painted skin (ctx.add(..., panel=True)); the creases are the
edges marked with ctx.crease (the rg_crease edge attribute). Faces marked with ctx.inner (a removable panel's
returned edge and inner face) are not skin: only outer skin is measured. Every edge within --crease-margin-mm of a
crease is left out, so the fold and the faces rolling into it are not counted.
Two checks run per panel:
  1. Adjacent-face dihedral angles (99th percentile and maximum, with location in mm).
  2. Multi-scale waviness (wave_mm): at interior outer-skin points at least --wave-radius-mm from panel borders and
     creases, a smooth local quadratic surface is fitted over neighbours within --wave-radius-mm. Pure curvature
     (cylinders, arches, crowns) fits closely; localized ripples and dents depart from the quadratic regardless of
     mesh subdivision density.
The evaluated mesh (as it renders) is measured; --base-mesh measures the mesh as modelled.
Writes <out>/fairness.json. Exit 1 when any panel is over a limit, 2 on bad input (no registered panels).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/fairness.py -- --out DIR [--project DIR] '
         '[--crease-margin-mm 10] [--max-p99-deg 2.5] [--max-deg 5] [--wave-radius-mm 60] [--max-wave-mm 1.0] '
         '[--base-mesh]')


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
    skin = ~md.inner()
    ok = good_poly[pa] & good_poly[pb] & skin[pa] & skin[pb]       # outer skin only
    inner, pa, pb = inner[ok], pa[ok], pb[ok]
    cosang = np.clip((pn[pa] * pn[pb]).sum(1), -1.0, 1.0)
    ang = np.degrees(np.arccos(cosang))
    mid = md.verts[md.edges[inner]].mean(1)
    if creases.any():
        ce = md.edges[creases]
        drop = creases[inner] | near(mid, md.verts[ce[:, 0]], md.verts[ce[:, 1]], margin)
        ang, mid = ang[~drop], mid[~drop]
    return ang, mid, int(creases.sum())


def measure_wave(md, creases, margin, radius, max_samples=2000):
    """Resolution-independent surface waviness: peak departure (scene units) of interior outer-skin vertices from
    a smooth local quadratic patch fitted within `radius` (excluding creases and outer-skin borders)."""
    from mathutils import kdtree
    if radius <= 0:
        return None, None, 0
    tris = md.outer_tris()
    if not len(tris):
        return None, None, 0
    v = md.verts[tris]
    tn = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    vn = np.zeros_like(md.verts)
    for k in range(3):
        np.add.at(vn, tris[:, k], tn)
    outer_verts = np.unique(tris)
    vlen = np.linalg.norm(vn[outer_verts], axis=1)
    good = vlen > 1e-18
    outer_verts = outer_verts[good]
    if len(outer_verts) < 16:
        return None, None, 0
    P = md.verts[outer_verts]
    N = vn[outer_verts] / vlen[good, None]

    # Outer-skin boundary edges (belong to only 1 outer polygon)
    skin = ~md.inner()
    npoly = len(md.poly_loop_total)
    poly_of_loop = np.repeat(np.arange(npoly), md.poly_loop_total)
    outer_loops = skin[poly_of_loop]
    outer_edge_counts = np.bincount(md.loop_edge[outer_loops], minlength=len(md.edges)) if len(md.edges) else np.zeros(0)
    border_mask = outer_edge_counts == 1

    # Candidate centres (deterministic sample if the mesh is very dense)
    if len(outer_verts) > max_samples:
        rng = np.random.default_rng(0)
        cand_idx = np.sort(rng.choice(len(outer_verts), size=max_samples, replace=False))
    else:
        cand_idx = np.arange(len(outer_verts))
    cand_P = P[cand_idx]
    keep = np.ones(len(cand_idx), bool)
    if border_mask.any():
        be = md.edges[border_mask]
        keep &= ~near(cand_P, md.verts[be[:, 0]], md.verts[be[:, 1]], radius)
    if creases.any():
        ce = md.edges[creases]
        keep &= ~near(cand_P, md.verts[ce[:, 0]], md.verts[ce[:, 1]], margin + radius)
    cand_idx = cand_idx[keep]
    if not len(cand_idx):
        return None, None, 0

    kd = kdtree.KDTree(len(P))
    for i, pt in enumerate(P):
        kd.insert(pt, i)
    kd.balance()

    worst, worst_p, tested = None, None, 0
    for ci in cand_idx:
        p0, n0 = P[ci], N[ci]
        hits = kd.find_range(p0, radius)
        if len(hits) < 12:
            continue
        nb = np.array([h[1] for h in hits], dtype=np.int64)
        nb = nb[(N[nb] @ n0) > 0.707]            # keep same-side smooth sheet (within 45 deg)
        if len(nb) < 12:
            continue
        ref = np.array([1.0, 0.0, 0.0]) if abs(n0[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        t1 = np.cross(n0, ref)
        t1 /= np.linalg.norm(t1)
        t2 = np.cross(n0, t1)
        d = P[nb] - p0
        u = (d @ t1) / radius
        w2 = (d @ t2) / radius
        z = d @ n0
        if np.ptp(u) < 0.6 or np.ptp(w2) < 0.6:   # need 2D spatial support inside the disc
            continue
        A = np.column_stack([np.ones(len(nb)), u, w2, u * u, u * w2, w2 * w2])
        coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        dep = float(np.percentile(np.abs(z - A @ coef), 95))   # 95th-percentile departure from smooth quadratic
        tested += 1
        if worst is None or dep > worst:
            worst, worst_p = dep, p0
    return worst, worst_p, tested


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--crease-margin-mm', type=float, default=10.0)
    ap.add_argument('--max-p99-deg', type=float, default=2.5)
    ap.add_argument('--max-deg', type=float, default=5.0)
    ap.add_argument('--wave-radius-mm', type=float, default=60.0)
    ap.add_argument('--max-wave-mm', type=float, default=1.0)
    ap.add_argument('--base-mesh', action='store_true')
    B.add_project_arg(ap)
    a = ap.parse(argv)
    if a.crease_margin_mm < 0 or a.wave_radius_mm < 0 or a.max_wave_mm <= 0:
        raise BadInput('--crease-margin-mm, --wave-radius-mm must be >= 0 and --max-wave-mm > 0')
    panels = B.registered('rg_panel')
    if not panels:
        raise BadInput('no panels: the scene has no object registered with ctx.add(..., panel=True)')
    names = ['rg_crease']
    unit = B.mm_per_unit()
    margin = a.crease_margin_mm / unit
    wrad = a.wave_radius_mm / unit
    rows, ok, found_any = {}, True, set()
    for ob in panels:
        md = BaseMesh(ob) if a.base_mesh else B.MeshData(ob, layers=True)
        cm, found = crease_mask(md, names)
        found_any |= set(found)
        ang, mid, ncrease = measure(md, cm, margin)
        wval, wpt, wtested = measure_wave(md, cm, margin, wrad)
        wave_mm = None if wval is None else float(wval * unit)
        if len(ang):
            i = int(np.argmax(ang))
            r = dict(p99_deg=float(np.percentile(ang, 99)), max_deg=float(ang[i]),
                     max_at_mm=(mid[i] * unit).tolist(), mean_deg=float(ang.mean()), edges=int(len(ang)),
                     wave_mm=wave_mm, wave_at_mm=(wpt * unit).tolist() if wpt is not None else None,
                     wave_samples=int(wtested))
            wave_ok = True if wave_mm is None else (wave_mm <= a.max_wave_mm)
            r['passed'] = r['p99_deg'] <= a.max_p99_deg and r['max_deg'] <= a.max_deg and wave_ok
        else:
            r = dict(p99_deg=None, max_deg=None, wave_mm=wave_mm, edges=0, passed=False,
                     note='no edges left to measure')
        r.update(crease_edges=ncrease, creases_found=found)
        ok &= r['passed']
        r['part'] = ob.get('rg_part', ob.name)
        rows[ob.name] = r
        print('PANEL %-24s edges %6d  p99 %6s  max %6s  wave %6s  %s' % (
            ob.name, r['edges'], '-' if r['p99_deg'] is None else '%.2f' % r['p99_deg'],
            '-' if r['max_deg'] is None else '%.2f' % r['max_deg'],
            '-' if r['wave_mm'] is None else '%.2fmm' % r['wave_mm'], 'pass' if r['passed'] else 'FAIL'))
    res = dict(max_p99_deg=a.max_p99_deg, max_deg=a.max_deg, max_wave_mm=a.max_wave_mm,
               wave_radius_mm=a.wave_radius_mm, crease_margin_mm=a.crease_margin_mm, creases=names,
               mesh='base' if a.base_mesh else 'evaluated', panels=rows, passed=bool(ok))
    save_json(os.path.join(a.out, 'fairness.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
