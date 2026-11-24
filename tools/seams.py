"""Measure body-to-body and glass-to-body panel seam gaps and flush steps.              (runs in Blender)

usage: blender -b <scene.blend> --python tools/seams.py -- --out DIR [--project DIR] [--seams FILE]
       [--build FILE] [--pair A:B] [--min-gap-mm 1.5] [--max-gap-mm 5.0] [--max-flush-mm 2.0]
       [--search-radius-mm 40] [--points 72] [--with-daylight] [--daylight-grid 192] [--name seams]

Checks declared adjacent panel/glass pairs (e.g. hood:bumper, fender:bumper, hatch_glass:hatch,
tail:quarter, quarter:rear_bumper, cant_rail:cpillar) from data/seams.json, build.json ("seams"), or
--pair A:B. For each pair, extracts each part's outer-skin boundary (excluding ctx.inner faces; using an
optional edge vertex group when given), isolates the mutually parallel mating seam segment within
--search-radius-mm, and measures:
  - tangential shut-line gap_mm (positive = separated, negative = overlapping): must stay in
    [--min-gap-mm, --max-gap-mm] (default 1.5 to 5.0 mm);
  - normal flush step flush_mm (+ = A proud of B, - = A sunk below B): |flush_mm| <= --max-flush-mm
    (default 2.0 mm).

With --with-daylight, also runs tools/daylight.py in the same Blender pass and writes <out>/daylight.json.
Writes <out>/<name>.json (default seams.json; gates.py reads seams*.json).
Exit 0 when all pairs pass (and daylight passes when --with-daylight), 1 when any fails, 2 on bad input.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/seams.py -- --out DIR [--project DIR] '
         '[--seams FILE | --pair A:B] [--min-gap-mm 1.5] [--max-gap-mm 5.0] [--max-flush-mm 2.0]')

DEFAULT_MIN_GAP_MM = 1.5
DEFAULT_MAX_GAP_MM = 5.0
DEFAULT_MAX_FLUSH_MM = 2.0
DEFAULT_SEARCH_RADIUS_MM = 40.0


def _sample_segments(segs, step):
    """Densify a list of boundary segments dicts into parallel numpy arrays.
    Each segment dict has p0, p1 (3,), tangent (3,), inward (3,), normal (3,).
    """
    pts, tangs, inwards, norms = [], [], [], []
    for s in segs:
        p0, p1 = np.asarray(s['p0'], float), np.asarray(s['p1'], float)
        seg_len = float(np.linalg.norm(p1 - p0))
        if seg_len < 1e-9:
            continue
        n = max(2, int(np.ceil(seg_len / max(step, 1e-6))) + 1)
        ts = np.linspace(0.0, 1.0, n)
        P = p0[None, :] + (p1 - p0)[None, :] * ts[:, None]
        pts.append(P)
        tangs.append(np.repeat(np.asarray(s['tangent'], float)[None, :], n, axis=0))
        inwards.append(np.repeat(np.asarray(s['inward'], float)[None, :], n, axis=0))
        norms.append(np.repeat(np.asarray(s['normal'], float)[None, :], n, axis=0))
    if not pts:
        return None
    return (np.concatenate(pts, axis=0), np.concatenate(tangs, axis=0),
            np.concatenate(inwards, axis=0), np.concatenate(norms, axis=0))


def measure_seam_geometry(segs_a, segs_b, min_gap_mm=DEFAULT_MIN_GAP_MM, max_gap_mm=DEFAULT_MAX_GAP_MM,
                          max_flush_mm=DEFAULT_MAX_FLUSH_MM, search_radius_mm=DEFAULT_SEARCH_RADIUS_MM,
                          n_points=72, unit=1000.0, parallel_cos=0.7, perp_cos=0.75):
    """Pure-NumPy geometric seam measurement between boundary segments of panel A and panel B.

    Coordinates in segs_a / segs_b are in scene units; `unit` converts scene units to mm (1000.0 for metres,
    1.0 if already in mm). Returns a measurement dict with min/max/mean gap_mm, flush_mm, and pass flags.
    """
    radius = float(search_radius_mm) / float(unit)
    step = max(radius / 12.0, 1.0 / float(unit))
    da = _sample_segments(segs_a, step)
    db = _sample_segments(segs_b, step)
    if da is None or db is None:
        return dict(samples_count=0, min_gap_mm=None, max_gap_mm=None, mean_gap_mm=None,
                    max_abs_flush_mm=None, min_flush_mm=None, max_flush_mm=None, mean_flush_mm=None,
                    gap_passed=False, flush_passed=False, passed=False,
                    note='part has no measurable outer-skin boundary')

    Pa, Ta, _Ia, Na = da
    Pb, Tb, Ib, Nb = db

    # Pairwise distances via scipy KDTree when available (fast on CPU), else chunked NumPy
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(Pb)
        dists, idxs = tree.query(Pa, distance_upper_bound=radius)
        valid = np.isfinite(dists) & (idxs < len(Pb))
    except ImportError:
        dists = np.full(len(Pa), np.inf, dtype=float)
        idxs = np.zeros(len(Pa), dtype=np.int64)
        chunk = 512
        for start in range(0, len(Pa), chunk):
            end = min(len(Pa), start + chunk)
            diff = Pa[start:end, None, :] - Pb[None, :, :]
            d2 = np.einsum('ijk,ijk->ij', diff, diff)
            jmin = np.argmin(d2, axis=1)
            dmin = np.sqrt(d2[np.arange(end - start), jmin])
            dists[start:end] = dmin
            idxs[start:end] = jmin
        valid = dists <= radius

    cand = np.flatnonzero(valid)
    if not len(cand):
        return dict(samples_count=0, min_gap_mm=None, max_gap_mm=None, mean_gap_mm=None,
                    max_abs_flush_mm=None, min_flush_mm=None, max_flush_mm=None, mean_flush_mm=None,
                    gap_passed=False, flush_passed=False, passed=False,
                    note='no mating boundary found within %.1f mm search radius' % search_radius_mm)

    gaps, flushes, pos_a, pos_b = [], [], [], []
    for i in cand:
        j = int(idxs[i])
        # Exclude perpendicular side edges meeting only near a corner
        if abs(float(np.dot(Ta[i], Tb[j]))) < parallel_cos:
            continue
        d = Pa[i] - Pb[j]
        n = Nb[j]
        n_avg = Na[i] + Nb[j]
        if float(np.linalg.norm(n_avg)) > 1e-6 and float(np.dot(Na[i], Nb[j])) > 0.5:
            n = n_avg / float(np.linalg.norm(n_avg))
        flush = float(np.dot(d, n))
        d_tang = d - flush * n
        tang_len = float(np.linalg.norm(d_tang))
        if tang_len > 1e-9:
            # Exclude points whose displacement runs mainly ALONG B's seam rather than ACROSS it
            if abs(float(np.dot(d_tang / tang_len, Tb[j]))) > perp_cos:
                continue
            # Signed gap: negative when A crosses into B's interior (inward tangent)
            sign = -1.0 if float(np.dot(d_tang, Ib[j])) > 0.0 else 1.0
            gap = sign * tang_len
        else:
            gap = 0.0
        gaps.append(gap * unit)
        flushes.append(flush * unit)
        pos_a.append((Pa[i] * unit).tolist())
        pos_b.append((Pb[j] * unit).tolist())

    if not gaps:
        return dict(samples_count=0, min_gap_mm=None, max_gap_mm=None, mean_gap_mm=None,
                    max_abs_flush_mm=None, min_flush_mm=None, max_flush_mm=None, mean_flush_mm=None,
                    gap_passed=False, flush_passed=False, passed=False,
                    note='no parallel mating edge found within %.1f mm search radius' % search_radius_mm)

    # Subsample evenly to ~n_points for compact JSON output while preserving worst extremes
    gaps_arr = np.asarray(gaps, float)
    flushes_arr = np.asarray(flushes, float)
    min_g_idx = int(np.argmin(gaps_arr))
    max_g_idx = int(np.argmax(gaps_arr))
    max_f_idx = int(np.argmax(np.abs(flushes_arr)))

    min_g = float(gaps_arr[min_g_idx])
    max_g = float(gaps_arr[max_g_idx])
    mean_g = float(gaps_arr.mean())
    max_abs_f = float(np.abs(flushes_arr[max_f_idx]))
    min_f = float(flushes_arr.min())
    max_f = float(flushes_arr.max())
    mean_f = float(flushes_arr.mean())

    gap_ok = (min_g >= float(min_gap_mm)) and (max_g <= float(max_gap_mm))
    flush_ok = max_abs_f <= float(max_flush_mm)

    # Pick representative sample indices
    if len(gaps) > n_points:
        keep = sorted(set(np.linspace(0, len(gaps) - 1, n_points, dtype=int).tolist() +
                          [min_g_idx, max_g_idx, max_f_idx]))
    else:
        keep = list(range(len(gaps)))
    samples = [dict(position_a_mm=[round(c, 2) for c in pos_a[k]],
                    position_b_mm=[round(c, 2) for c in pos_b[k]],
                    gap_mm=round(float(gaps_arr[k]), 3),
                    flush_mm=round(float(flushes_arr[k]), 3)) for k in keep]

    return dict(
        samples_count=int(len(gaps)),
        min_gap_mm=round(min_g, 3),
        max_gap_mm=round(max_g, 3),
        mean_gap_mm=round(mean_g, 3),
        max_abs_flush_mm=round(max_abs_f, 3),
        min_flush_mm=round(min_f, 3),
        max_flush_mm=round(max_f, 3),
        mean_flush_mm=round(mean_f, 3),
        worst_gap_at_mm=[round(c, 2) for c in pos_a[max_g_idx if (max_g - max_gap_mm) >= (min_gap_mm - min_g) else min_g_idx]],
        worst_flush_at_mm=[round(c, 2) for c in pos_a[max_f_idx]],
        gap_passed=bool(gap_ok),
        flush_passed=bool(flush_ok),
        passed=bool(gap_ok and flush_ok),
        points=samples,
    )


def _extract_blender_boundary(objs, edge_group=None):
    """Extract outer-skin boundary segments with edge tangents, inward tangents and outward normals."""
    import _blender as B

    segs = []
    for ob in objs:
        md = B.MeshData(ob, layers=True)
        if not len(md.tris):
            continue
        skin = ~md.inner()
        npoly = len(md.poly_loop_total)
        poly_of_loop = np.repeat(np.arange(npoly), md.poly_loop_total)

        # Compute polygon outward normals (area-weighted from loop triangles)
        nrm, area = md.tri_normals()
        pn = np.zeros((npoly, 3), float)
        np.add.at(pn, md.tri_poly, nrm * area[:, None])
        pl = np.linalg.norm(pn, axis=1)
        good_p = pl > 1e-18
        pn[good_p] /= pl[good_p, None]

        # Polygon centroids (for inward direction)
        poly_centers = np.zeros((npoly, 3), float)
        for pi in range(npoly):
            st = int(md.poly_loop_start[pi])
            cnt = int(md.poly_loop_total[pi])
            es = md.loop_edge[st:st + cnt]
            vs = np.unique(md.edges[es])
            if len(vs):
                poly_centers[pi] = md.verts[vs].mean(0)

        # Map each edge to its outer-skin polygons
        outer_loops = skin[poly_of_loop]
        edge_polys = {}
        for li in np.flatnonzero(outer_loops):
            ei = int(md.loop_edge[li])
            pi = int(poly_of_loop[li])
            edge_polys.setdefault(ei, []).append(pi)

        eff_group = edge_group
        if not eff_group and 'rg_seat' in getattr(md, 'vgroups', {}):
            # Only fall back to rg_seat if there are no outer-skin open borders (closed solid part)
            if not any(len(ps) == 1 for ps in edge_polys.values()):
                eff_group = 'rg_seat'

        if eff_group:
            g = getattr(md, 'vgroups', {}).get(eff_group)
            if not g:
                continue
            cand_edges = [ei for ei, (va, vb) in enumerate(md.edges) if va in g and vb in g]
        else:
            cand_edges = [ei for ei, ps in edge_polys.items() if len(ps) == 1]

        for ei in cand_edges:
            va, vb = int(md.edges[ei][0]), int(md.edges[ei][1])
            p0, p1 = md.verts[va], md.verts[vb]
            ev = p1 - p0
            elen = float(np.linalg.norm(ev))
            if elen < 1e-9:
                continue
            tang = ev / elen
            ps = edge_polys.get(ei, [])
            if ps:
                n = pn[ps].mean(0)
                nlen = float(np.linalg.norm(n))
                n = n / nlen if nlen > 1e-9 else np.array([0.0, 0.0, 1.0])
                mid = 0.5 * (p0 + p1)
                c_vec = poly_centers[ps[0]] - mid
                c_vec = c_vec - float(np.dot(c_vec, tang)) * tang
                c_vec = c_vec - float(np.dot(c_vec, n)) * n
                clen = float(np.linalg.norm(c_vec))
                inward = c_vec / clen if clen > 1e-9 else np.cross(n, tang)
            else:
                n = np.array([0.0, 0.0, 1.0])
                inward = np.cross(n, tang)
            segs.append(dict(p0=p0, p1=p1, tangent=tang, inward=inward, normal=n))
    return segs


def _resolve_part(name):
    import _blender as B
    obs = B.part_objects(name)
    if not obs:
        obs = [o for o in B.find_objects(name) if o.type in B.GEOMETRY]
    return obs


def measure_seam_pair(a_name, b_name, min_gap_mm=DEFAULT_MIN_GAP_MM, max_gap_mm=DEFAULT_MAX_GAP_MM,
                      max_flush_mm=DEFAULT_MAX_FLUSH_MM, search_radius_mm=DEFAULT_SEARCH_RADIUS_MM,
                      n_points=72, edge_group_a=None, edge_group_b=None, kind='body', pair_name=None):
    """Measure one adjacent panel/glass pair in the current Blender scene."""
    import _blender as B

    u = B.mm_per_unit()
    row = dict(
        name=pair_name or ('%s <-> %s' % (a_name, b_name)),
        a=a_name,
        b=b_name,
        kind=kind,
        limit_min_gap_mm=float(min_gap_mm),
        limit_max_gap_mm=float(max_gap_mm),
        limit_max_flush_mm=float(max_flush_mm),
    )
    a_obs, b_obs = _resolve_part(a_name), _resolve_part(b_name)
    if not a_obs or not b_obs:
        missing = ('part %r' % a_name) if not a_obs else ('part %r' % b_name)
        row.update(samples_count=0, min_gap_mm=None, max_gap_mm=None, mean_gap_mm=None,
                   max_abs_flush_mm=None, min_flush_mm=None, max_flush_mm=None, mean_flush_mm=None,
                   gap_passed=False, flush_passed=False, passed=False,
                   note='%s is not in the scene' % missing)
        return row

    segs_a = _extract_blender_boundary(a_obs, edge_group=edge_group_a)
    segs_b = _extract_blender_boundary(b_obs, edge_group=edge_group_b)
    if not segs_a or not segs_b:
        which = a_name if not segs_a else b_name
        row.update(samples_count=0, min_gap_mm=None, max_gap_mm=None, mean_gap_mm=None,
                   max_abs_flush_mm=None, min_flush_mm=None, max_flush_mm=None, mean_flush_mm=None,
                   gap_passed=False, flush_passed=False, passed=False,
                   note='part %r has no outer-skin boundary edge (mark closed solids with ctx.seat_edge)' % which)
        return row

    res = measure_seam_geometry(
        segs_a, segs_b,
        min_gap_mm=min_gap_mm, max_gap_mm=max_gap_mm, max_flush_mm=max_flush_mm,
        search_radius_mm=search_radius_mm, n_points=n_points, unit=u,
    )
    row.update(res)
    return row


def load_seam_pairs(project, seams_file=None, build_file=None, cli_pairs=None,
                    default_min_gap=DEFAULT_MIN_GAP_MM, default_max_gap=DEFAULT_MAX_GAP_MM,
                    default_max_flush=DEFAULT_MAX_FLUSH_MM, default_search_radius=DEFAULT_SEARCH_RADIUS_MM):
    """Collect declared seam pairs from CLI --pair, seams.json, and/or build.json."""
    pairs = []
    if cli_pairs:
        for raw in cli_pairs:
            for tok in raw.split(','):
                tok = tok.strip()
                if not tok:
                    continue
                if ':' not in tok:
                    raise BadInput('--pair entry %r must be formatted as partA:partB' % tok)
                a_nm, b_nm = [x.strip() for x in tok.split(':', 1)]
                if not a_nm or not b_nm or a_nm == b_nm:
                    raise BadInput('invalid --pair %r' % tok)
                pairs.append(dict(a=a_nm, b=b_nm, min_gap_mm=default_min_gap, max_gap_mm=default_max_gap,
                                  max_flush_mm=default_max_flush, search_radius_mm=default_search_radius,
                                  kind='body'))
        return pairs

    sp = seams_file or os.path.join(project, 'data', 'seams.json')
    if seams_file or os.path.isfile(sp):
        cfg = F.seams(load_json(sp, 'seams file'), os.path.basename(sp))
        g_min = cfg.get('min_gap_mm', default_min_gap)
        g_max = cfg.get('max_gap_mm', default_max_gap)
        g_fl = cfg.get('max_flush_mm', default_max_flush)
        g_sr = cfg.get('search_radius_mm', default_search_radius)
        for p in cfg['pairs']:
            pairs.append(dict(
                a=str(p['a']), b=str(p['b']),
                name=p.get('name'),
                kind=p.get('kind', 'body'),
                min_gap_mm=float(p.get('min_gap_mm', g_min)),
                max_gap_mm=float(p.get('max_gap_mm', g_max)),
                max_flush_mm=float(p.get('max_flush_mm', g_fl)),
                search_radius_mm=float(p.get('search_radius_mm', g_sr)),
                edge_group_a=p.get('edge_group_a'),
                edge_group_b=p.get('edge_group_b'),
            ))

    bp = build_file or os.path.join(project, 'data', 'build.json')
    if os.path.isfile(bp):
        build = F.build(load_json(bp, 'build list'))
        seen = {(p['a'], p['b']) for p in pairs}
        for e in build:
            for raw_p in (e.get('seams') or []):
                key = (str(raw_p['a']), str(raw_p['b']))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(dict(
                    a=key[0], b=key[1],
                    name=raw_p.get('name'),
                    kind=raw_p.get('kind', 'body'),
                    min_gap_mm=float(raw_p.get('min_gap_mm', default_min_gap)),
                    max_gap_mm=float(raw_p.get('max_gap_mm', default_max_gap)),
                    max_flush_mm=float(raw_p.get('max_flush_mm', default_max_flush)),
                    search_radius_mm=float(raw_p.get('search_radius_mm', default_search_radius)),
                    edge_group_a=raw_p.get('edge_group_a'),
                    edge_group_b=raw_p.get('edge_group_b'),
                ))
    return pairs


def evaluate_pairs(pairs, n_points=72):
    rows = []
    for p in pairs:
        r = measure_seam_pair(
            p['a'], p['b'],
            min_gap_mm=p['min_gap_mm'],
            max_gap_mm=p['max_gap_mm'],
            max_flush_mm=p['max_flush_mm'],
            search_radius_mm=p['search_radius_mm'],
            n_points=n_points,
            edge_group_a=p.get('edge_group_a'),
            edge_group_b=p.get('edge_group_b'),
            kind=p.get('kind', 'body'),
            pair_name=p.get('name'),
        )
        rows.append(r)
        if r.get('note'):
            detail = r['note']
        else:
            detail = 'gap %.2f..%.2f mm  flush %.2f mm' % (r['min_gap_mm'], r['max_gap_mm'], r['max_abs_flush_mm'])
        print('SEAM %-28s %s  %s' % (r['name'], detail, 'pass' if r['passed'] else 'FAIL'))
    return rows


def main(argv):
    import _blender as B

    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seams', default=None)
    ap.add_argument('--build', default=None)
    ap.add_argument('--pair', action='append', default=[])
    ap.add_argument('--min-gap-mm', type=float, default=DEFAULT_MIN_GAP_MM)
    ap.add_argument('--max-gap-mm', type=float, default=DEFAULT_MAX_GAP_MM)
    ap.add_argument('--max-flush-mm', type=float, default=DEFAULT_MAX_FLUSH_MM)
    ap.add_argument('--search-radius-mm', type=float, default=DEFAULT_SEARCH_RADIUS_MM)
    ap.add_argument('--points', type=int, default=72)
    ap.add_argument('--with-daylight', action='store_true')
    ap.add_argument('--daylight-grid', type=int, default=192)
    ap.add_argument('--name', default='seams')
    B.add_project_arg(ap)
    a = ap.parse(argv)

    if a.min_gap_mm < 0 or a.max_gap_mm <= a.min_gap_mm or a.max_flush_mm <= 0 or a.search_radius_mm <= 0:
        raise BadInput('invalid seam gap/flush/search-radius limits')
    if a.points < 4:
        raise BadInput('--points must be at least 4')

    project = B.project_dir(a)
    pairs = load_seam_pairs(
        project, seams_file=a.seams, build_file=a.build, cli_pairs=a.pair,
        default_min_gap=a.min_gap_mm, default_max_gap=a.max_gap_mm,
        default_max_flush=a.max_flush_mm, default_search_radius=a.search_radius_mm,
    )
    if not pairs:
        raise BadInput('no seam pairs configured (provide data/seams.json, build.json seams, or --pair A:B)')

    rows = evaluate_pairs(pairs, n_points=a.points)
    ok = all(r['passed'] for r in rows)
    res = dict(
        min_gap_mm=a.min_gap_mm,
        max_gap_mm=a.max_gap_mm,
        max_flush_mm=a.max_flush_mm,
        search_radius_mm=a.search_radius_mm,
        pairs=rows,
        passed=bool(ok),
    )

    if a.with_daylight:
        import daylight
        dl = daylight.run_daylight(grid=a.daylight_grid)
        save_json(os.path.join(a.out, 'daylight.json'), dl)
        res['daylight_passed'] = bool(dl['passed'])
        ok = ok and bool(dl['passed'])
        res['passed'] = bool(ok)

    save_json(os.path.join(a.out, a.name + '.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    import _blender as B
    B.run(main)
