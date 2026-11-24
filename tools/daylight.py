"""CPU daylight-leak ray gate: cast rays from front, rear, left, right and 3/4 views.   (runs in Blender)

usage: blender -b <scene.blend> --python tools/daylight.py -- --out DIR [--project DIR]
       [--views front,rear,left,right,front-left,front-right,rear-left,rear-right] [--grid 192]
       [--cameras FILE] [--glass-patterns PATTERNS] [--ignore-silhouette PATTERNS] [--wedge-px 2]
       [--max-leaks 0] [--name daylight]

Casts a fast CPU BVH ray grid through each view across the tight bounding box of the visible exterior
vehicle. Fails if any non-glass ray inside the vehicle's body silhouette:
  - hits the background (an enclosed hole/slit/slot, or a narrow wedge gap between two body parts), OR
  - hits a panel's interior backface (a polygon marked with ctx.inner / rg_inner, or the backface of an
    rg_panel painted surface).

Rays whose first hit is glass (rg_glass property, transmissive material, or name matching --glass-patterns)
are allowed to see through to the interior or background. Detached accessories (wheels, tyres, mirrors,
wings, antennas by default via --ignore-silhouette) still block rays, but do not form enclosed silhouette
holes on their own (preventing false positives between wheel spokes or under wing struts).

Writes <out>/<name>.json (default daylight.json; gates.py reads daylight*.json).
Exit 0 when leaks <= --max-leaks, 1 when any leak exceeds the limit, 2 on bad input.
"""
from collections import deque
import fnmatch
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/daylight.py -- --out DIR [--project DIR] '
         '[--views front,rear,left,right,front-left,front-right,rear-left,rear-right] [--grid 192]')

DEFAULT_VIEWS = ('front', 'rear', 'left', 'right', 'front-left', 'front-right', 'rear-left', 'rear-right')
RING_HEADINGS = {
    'front': 0.0,
    'front-left': 45.0,
    'left': 90.0,
    'rear-left': 135.0,
    'rear': 180.0,
    'rear-right': 225.0,
    'right': 270.0,
    'front-right': 315.0,
}
DEFAULT_GLASS_PATTERNS = ('*glass*', '*window*', '*windscreen*', '*windshield*', '*glazing*', '*lens*',
                          '*lamp_cover*', '*canopy*')
DEFAULT_IGNORE_SILHOUETTE = ('*wheel*', '*tyre*', '*tire*', '*rim*', '*spoke*', '*wing*', '*spoiler*',
                             '*mirror*', '*antenna*')


def match_any(text, patterns):
    s = str(text or '').lower()
    return any(fnmatch.fnmatchcase(s, p.lower()) for p in patterns)


def enclosed_holes(mask):
    """Boolean mask of False pixels strictly enclosed inside True pixels (not reachable from grid border)."""
    m = np.asarray(mask, dtype=bool)
    h, w = m.shape
    if h < 3 or w < 3 or not m.any():
        return np.zeros((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)
    q = deque()
    for i in range(w):
        if not m[0, i] and not visited[0, i]:
            visited[0, i] = True
            q.append((0, i))
        if not m[h - 1, i] and not visited[h - 1, i]:
            visited[h - 1, i] = True
            q.append((h - 1, i))
    for j in range(1, h - 1):
        if not m[j, 0] and not visited[j, 0]:
            visited[j, 0] = True
            q.append((j, 0))
        if not m[j, w - 1] and not visited[j, w - 1]:
            visited[j, w - 1] = True
            q.append((j, w - 1))
    while q:
        r, c = q.popleft()
        if r > 0 and not m[r - 1, c] and not visited[r - 1, c]:
            visited[r - 1, c] = True
            q.append((r - 1, c))
        if r + 1 < h and not m[r + 1, c] and not visited[r + 1, c]:
            visited[r + 1, c] = True
            q.append((r + 1, c))
        if c > 0 and not m[r, c - 1] and not visited[r, c - 1]:
            visited[r, c - 1] = True
            q.append((r, c - 1))
        if c + 1 < w and not m[r, c + 1] and not visited[r, c + 1]:
            visited[r, c + 1] = True
            q.append((r, c + 1))
    return (~m) & (~visited)


def edge_wedge_gaps(sil_mask, bg_mask, obj_ids, radius=2):
    """Background pixels bridged within `radius` cells horizontally or vertically between two DIFFERENT
    body-silhouette objects (catches open bumper-to-fender or tail-lamp wedge gaps at the silhouette edge
    without false positives on smooth convex edges of one panel or wide wheel arches)."""
    sil = np.asarray(sil_mask, dtype=bool)
    bg = np.asarray(bg_mask, dtype=bool)
    oids = np.asarray(obj_ids, dtype=np.int32)
    h, w = sil.shape
    out = np.zeros((h, w), dtype=bool)
    if radius < 1 or not bg.any() or not sil.any():
        return out
    ys, xs = np.nonzero(bg)
    for y, x in zip(ys, xs):
        # Horizontal bridge between two different silhouette objects within `radius` cells
        left_obj = -1
        for dx in range(1, radius + 1):
            if x - dx < 0:
                break
            if sil[y, x - dx]:
                left_obj = int(oids[y, x - dx])
                break
        if left_obj >= 0:
            for dx in range(1, radius + 1):
                if x + dx >= w:
                    break
                if sil[y, x + dx]:
                    if int(oids[y, x + dx]) != left_obj:
                        out[y, x] = True
                    break
        if out[y, x]:
            continue
        # Vertical bridge between two different silhouette objects within `radius` cells
        up_obj = -1
        for dy in range(1, radius + 1):
            if y - dy < 0:
                break
            if sil[y - dy, x]:
                up_obj = int(oids[y - dy, x])
                break
        if up_obj >= 0:
            for dy in range(1, radius + 1):
                if y + dy >= h:
                    break
                if sil[y + dy, x]:
                    if int(oids[y + dy, x]) != up_obj:
                        out[y, x] = True
                    break
    return out


def classify_grid(hit_kind, sil_mask, obj_ids, wedge_px=2):
    """Classify a 2D ray grid into daylight leaks.

    hit_kind codes:
      0 = background (no hit)
      1 = solid exterior (non-glass, non-inner, front-facing)
      2 = glass (first hit is glass -> allowed)
      3 = inner_face (first non-glass hit is marked rg_inner)
      4 = panel_backface (first non-glass hit is backface of an rg_panel)

    Returns dict of boolean masks: background_holes, wedge_gaps, inner_leaks, backface_leaks, all_leaks.
    """
    hk = np.asarray(hit_kind, dtype=np.int8)
    sil = np.asarray(sil_mask, dtype=bool)
    bg = hk == 0
    holes = enclosed_holes(sil) & bg
    wedges = edge_wedge_gaps(sil, bg & ~holes, obj_ids, radius=int(wedge_px))
    inner = hk == 3
    backface = hk == 4
    all_leaks = holes | wedges | inner | backface
    return dict(
        background_holes=holes,
        wedge_gaps=wedges,
        inner_leaks=inner,
        backface_leaks=backface,
        all_leaks=all_leaks,
    )


def _material_is_glass(mat, glass_patterns):
    if mat is None:
        return False
    if match_any(mat.name, glass_patterns):
        return True
    try:
        nt = mat.node_tree
        if nt is not None:
            for n in nt.nodes:
                if n.type == 'BSDF_PRINCIPLED':
                    tr = n.inputs.get('Transmission Weight') or n.inputs.get('Transmission')
                    if tr is not None and float(tr.default_value) > 0.25:
                        return True
                    al = n.inputs.get('Alpha')
                    if al is not None and float(al.default_value) < 0.9:
                        return True
                elif n.type in ('BSDF_GLASS', 'BSDF_TRANSPARENT'):
                    return True
    except Exception:
        pass
    return False


def _build_scene_bvh(objs, glass_patterns, ignore_sil_patterns):
    import _blender as B
    from mathutils.bvhtree import BVHTree

    dg = B.depsgraph()
    all_verts = []
    all_tris = []
    tri_obj = []
    tri_inner = []
    tri_panel = []
    tri_glass = []
    tri_sil = []
    tri_normals = []
    obj_meta = []

    for obj_idx, ob in enumerate(objs):
        md = B.MeshData(ob, dg=dg, layers=True)
        if not len(md.tris):
            continue
        ev = ob.evaluated_get(dg)
        slot_glass = []
        for slot in ev.material_slots:
            slot_glass.append(_material_is_glass(slot.material, glass_patterns))
        part_name = str(ob.get('rg_part', ob.name))
        obj_glass = bool(ob.get('rg_glass', False)) or match_any(ob.name, glass_patterns) or match_any(
            part_name, glass_patterns)
        is_panel = bool(ob.get('rg_panel', False))
        is_exterior = bool(ob.get('rg_exterior', True))
        in_sil = (is_exterior and not ob.get('rg_steer')
                  and not match_any(ob.name, ignore_sil_patterns)
                  and not match_any(part_name, ignore_sil_patterns))

        base = len(all_verts)
        all_verts.extend(tuple(float(c) for c in v) for v in md.verts)
        all_tris.extend((int(t[0]) + base, int(t[1]) + base, int(t[2]) + base) for t in md.tris)

        inner_poly = md.inner()
        t_inner = inner_poly[md.tri_poly]
        t_mat = md.poly_material[md.tri_poly]
        if obj_glass:
            t_glass = np.ones(len(md.tris), dtype=bool)
        elif slot_glass:
            sg = np.array(slot_glass, dtype=bool)
            valid = (t_mat >= 0) & (t_mat < len(sg))
            t_glass = np.zeros(len(md.tris), dtype=bool)
            t_glass[valid] = sg[t_mat[valid]]
        else:
            t_glass = np.zeros(len(md.tris), dtype=bool)

        nrm, _ = md.tri_normals()
        nt = len(md.tris)
        tri_obj.append(np.full(nt, obj_idx, dtype=np.int32))
        tri_inner.append(t_inner.astype(bool))
        tri_panel.append(np.full(nt, is_panel, dtype=bool))
        tri_glass.append(t_glass)
        tri_sil.append(np.full(nt, in_sil, dtype=bool))
        tri_normals.append(nrm)
        obj_meta.append(dict(name=ob.name, part=part_name, panel=is_panel, exterior=is_exterior,
                             glass=obj_glass, in_silhouette=in_sil))

    if not all_tris:
        raise BadInput('the scene has no triangles to raycast')

    bvh = BVHTree.FromPolygons(all_verts, all_tris)
    return dict(
        bvh=bvh,
        obj_meta=obj_meta,
        tri_obj=np.concatenate(tri_obj),
        tri_inner=np.concatenate(tri_inner),
        tri_panel=np.concatenate(tri_panel),
        tri_glass=np.concatenate(tri_glass),
        tri_sil=np.concatenate(tri_sil),
        tri_normals=np.concatenate(tri_normals),
    )


def _ortho_view_basis(view_name, lo, hi, margin=0.08):
    """Return (origin_center, right, up, forward, width_u, height_u, far) for a tight orthographic
    CPU ray grid looking at the vehicle from `view_name` (front, rear, left, right, or 3/4)."""
    if view_name not in RING_HEADINGS:
        raise BadInput('unknown daylight view %r (known: %s)' % (view_name, ', '.join(DEFAULT_VIEWS)))
    deg = RING_HEADINGS[view_name]
    r = math.radians(deg)
    # Camera direction from vehicle toward camera (same convention as orbit.py: X rear, Y right, Z up)
    cam_dir = np.array([-math.cos(r), -math.sin(r), 0.0], dtype=float)
    fwd = -cam_dir
    world_up = np.array([0.0, 0.0, 1.0], dtype=float)
    right = np.cross(fwd, world_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)

    corners = np.array([(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    centre = (lo + hi) / 2.0
    rel = corners - centre
    u_proj = rel @ right
    v_proj = rel @ up
    d_proj = rel @ fwd
    span_u = max(float(u_proj.max() - u_proj.min()), 1e-3)
    span_v = max(float(v_proj.max() - v_proj.min()), 1e-3)
    depth = max(float(d_proj.max() - d_proj.min()), 1e-3)

    # Extra margin ensures the outer 1-cell border of the grid is outside the vehicle silhouette
    w_u = span_u * (1.0 + 2.0 * margin)
    h_v = span_v * (1.0 + 2.0 * margin)
    u_mid = 0.5 * (u_proj.min() + u_proj.max())
    v_mid = 0.5 * (v_proj.min() + v_proj.max())
    cam_centre = centre + right * u_mid + up * v_mid - fwd * (depth * 1.5 + 1.0)
    far = depth * 3.0 + 2.0
    return cam_centre, right, up, fwd, w_u, h_v, far


def run_daylight(views=DEFAULT_VIEWS, grid=192, cameras_dict=None, glass_patterns=DEFAULT_GLASS_PATTERNS,
                 ignore_sil_patterns=DEFAULT_IGNORE_SILHOUETTE, wedge_px=2, max_leaks=0, max_samples=50):
    """Run the CPU daylight-leak check on the current Blender scene and return the JSON-ready dict."""
    import _blender as B
    import kit
    from mathutils import Vector

    objs = B.visible_geometry()
    if not objs:
        raise BadInput('the scene has no visible geometry')
    ext_objs = B.exterior_geometry() or objs
    lo, hi = B.bbox(ext_objs)
    u = B.mm_per_unit()
    scene = _build_scene_bvh(objs, glass_patterns, ignore_sil_patterns)
    bvh = scene['bvh']
    tri_obj = scene['tri_obj']
    tri_inner = scene['tri_inner']
    tri_panel = scene['tri_panel']
    tri_glass = scene['tri_glass']
    tri_sil = scene['tri_sil']
    tri_normals = scene['tri_normals']
    obj_meta = scene['obj_meta']

    view_results = {}
    total_bg = total_wedge = total_inner = total_back = 0

    for v in views:
        hit_kind = np.zeros((grid, grid), dtype=np.int8)
        sil_mask = np.zeros((grid, grid), dtype=bool)
        obj_ids = np.full((grid, grid), -1, dtype=np.int32)
        hit_pos = np.full((grid, grid, 3), np.nan, dtype=np.float64)

        if cameras_dict is not None:
            c = cameras_dict[v]
            cam = B.camera_from_view(v, c)
            W, H = int(c['width']), int(c['height'])
            far = float(np.linalg.norm(hi - lo)) * 4 + (cam.matrix_world.translation - Vector((lo + hi) / 2)).length * 2
            undo = kit.steer(float(c['steer_deg']))
            try:
                for j in range(grid):
                    py = (j + 0.5) * H / grid - 0.5
                    for i in range(grid):
                        px = (i + 0.5) * W / grid - 0.5
                        o, d = B.pixel_ray(cam, px, py, W, H)
                        loc, _nor, idx, _dist = bvh.ray_cast(o, d, far)
                        if loc is None:
                            continue
                        oid = int(tri_obj[idx])
                        obj_ids[j, i] = oid
                        hit_pos[j, i] = (loc.x, loc.y, loc.z)
                        if tri_glass[idx]:
                            hit_kind[j, i] = 2
                            sil_mask[j, i] = bool(tri_sil[idx])
                        elif tri_inner[idx]:
                            hit_kind[j, i] = 3
                            sil_mask[j, i] = True
                        elif tri_panel[idx] and float(tri_normals[idx, 0] * d.x + tri_normals[idx, 1] * d.y +
                                                      tri_normals[idx, 2] * d.z) > 0.0:
                            hit_kind[j, i] = 4
                            sil_mask[j, i] = True
                        else:
                            hit_kind[j, i] = 1
                            sil_mask[j, i] = bool(tri_sil[idx])
            finally:
                undo()
        else:
            cam_centre, right, up, fwd, w_u, h_v, far = _ortho_view_basis(v, lo, hi)
            d_vec = Vector((float(fwd[0]), float(fwd[1]), float(fwd[2])))
            d_np = fwd
            us = np.linspace(-0.5 * w_u, 0.5 * w_u, grid)
            vs = np.linspace(0.5 * h_v, -0.5 * h_v, grid)
            for j, vv in enumerate(vs):
                row_base = cam_centre + up * vv
                for i, uu in enumerate(us):
                    orig = row_base + right * uu
                    loc, _nor, idx, _dist = bvh.ray_cast(Vector((float(orig[0]), float(orig[1]), float(orig[2]))),
                                                         d_vec, far)
                    if loc is None:
                        continue
                    oid = int(tri_obj[idx])
                    obj_ids[j, i] = oid
                    hit_pos[j, i] = (loc.x, loc.y, loc.z)
                    if tri_glass[idx]:
                        hit_kind[j, i] = 2
                        sil_mask[j, i] = bool(tri_sil[idx])
                    elif tri_inner[idx]:
                        hit_kind[j, i] = 3
                        sil_mask[j, i] = True
                    elif tri_panel[idx] and float(np.dot(tri_normals[idx], d_np)) > 0.0:
                        hit_kind[j, i] = 4
                        sil_mask[j, i] = True
                    else:
                        hit_kind[j, i] = 1
                        sil_mask[j, i] = bool(tri_sil[idx])

        cls = classify_grid(hit_kind, sil_mask, obj_ids, wedge_px=wedge_px)
        n_bg = int(cls['background_holes'].sum())
        n_wedge = int(cls['wedge_gaps'].sum())
        n_inner = int(cls['inner_leaks'].sum())
        n_back = int(cls['backface_leaks'].sum())
        n_leaks = int(cls['all_leaks'].sum())
        total_bg += n_bg
        total_wedge += n_wedge
        total_inner += n_inner
        total_back += n_back

        samples = []
        for label, mask in (('background_hole', cls['background_holes']),
                            ('wedge_gap', cls['wedge_gaps']),
                            ('inner_face', cls['inner_leaks']),
                            ('panel_backface', cls['backface_leaks'])):
            if len(samples) >= max_samples:
                break
            ys, xs = np.nonzero(mask)
            for y, x in zip(ys, xs):
                if len(samples) >= max_samples:
                    break
                oid = int(obj_ids[y, x])
                meta = obj_meta[oid] if 0 <= oid < len(obj_meta) else None
                pos = hit_pos[y, x]
                samples.append(dict(
                    kind=label,
                    grid_xy=[int(x), int(y)],
                    object=meta['name'] if meta else None,
                    part=meta['part'] if meta else None,
                    position_mm=[round(float(c * u), 2) for c in pos] if np.all(np.isfinite(pos)) else None,
                ))

        view_results[v] = dict(
            grid=int(grid),
            rays_tested=int(grid * grid),
            silhouette_rays=int(sil_mask.sum()),
            glass_rays=int((hit_kind == 2).sum()),
            background_leaks=n_bg,
            wedge_leaks=n_wedge,
            inner_leaks=n_inner,
            backface_leaks=n_back,
            total_leaks=n_leaks,
            passed=n_leaks <= max_leaks,
            samples=samples,
        )
        print('DAYLIGHT %-12s sil %5d  glass %4d  bg %3d  wedge %3d  inner %3d  back %3d  %s' % (
            v, int(sil_mask.sum()), int((hit_kind == 2).sum()), n_bg, n_wedge, n_inner, n_back,
            'pass' if n_leaks <= max_leaks else 'FAIL'))

    total_leaks = total_bg + total_wedge + total_inner + total_back
    return dict(
        mode='cameras' if cameras_dict is not None else 'standard',
        grid=int(grid),
        wedge_px=int(wedge_px),
        max_leaks=int(max_leaks),
        views_checked=list(views),
        background_leaks=total_bg,
        wedge_leaks=total_wedge,
        inner_leaks=total_inner,
        backface_leaks=total_back,
        total_leaks=total_leaks,
        passed=total_leaks <= max_leaks,
        views=view_results,
    )


def main(argv):
    import _blender as B
    import _formats as F

    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--views', default='')
    ap.add_argument('--grid', type=int, default=192)
    ap.add_argument('--cameras', default=None)
    ap.add_argument('--glass-patterns', default='')
    ap.add_argument('--ignore-silhouette', default='')
    ap.add_argument('--wedge-px', type=int, default=2)
    ap.add_argument('--max-leaks', type=int, default=0)
    ap.add_argument('--name', default='daylight')
    B.add_project_arg(ap)
    a = ap.parse(argv)

    if not 16 <= a.grid <= 1024:
        raise BadInput('--grid must be between 16 and 1024')
    if a.wedge_px < 0 or a.wedge_px > 16:
        raise BadInput('--wedge-px must be between 0 and 16')
    if a.max_leaks < 0:
        raise BadInput('--max-leaks must be >= 0')

    cams = None
    if a.cameras:
        cams = F.cameras(load_json(a.cameras, 'cameras file'))
        views = B.globs(a.views) or list(cams)
        for v in views:
            if v not in cams:
                raise BadInput('view %r is not in cameras.json' % v)
    else:
        views = B.globs(a.views) or list(DEFAULT_VIEWS)
        for v in views:
            if v not in RING_HEADINGS:
                raise BadInput('unknown view %r (known: %s)' % (v, ', '.join(DEFAULT_VIEWS)))

    glass_patterns = tuple(B.globs(a.glass_patterns)) if a.glass_patterns else DEFAULT_GLASS_PATTERNS
    ignore_sil = tuple(B.globs(a.ignore_silhouette)) if a.ignore_silhouette else DEFAULT_IGNORE_SILHOUETTE

    res = run_daylight(
        views=views,
        grid=a.grid,
        cameras_dict=cams,
        glass_patterns=glass_patterns,
        ignore_sil_patterns=ignore_sil,
        wedge_px=a.wedge_px,
        max_leaks=a.max_leaks,
    )
    save_json(os.path.join(a.out, a.name + '.json'), res)
    print('daylight leaks:', res['total_leaks'], 'PASS' if res['passed'] else 'FAIL')
    return EXIT_OK if res['passed'] else EXIT_GATE


if __name__ == '__main__':
    import _blender as B
    B.run(main)
