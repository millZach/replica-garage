"""List every surface camera rays pass through, and find double skins.                   (runs in Blender)

usage: blender -b <scene.blend> --python tools/rays.py -- --out DIR [--project DIR] [--cameras FILE] [--landmarks FILE]
       [--grid 64 | --pixels PIXELS_FILE] [--stack-mm 10] [--views a,b] [--max-hits 32] [--name rays]

Cameras come from cameras.json (default <project>/data/cameras.json); each view is rendered at its steer_deg.
--grid N (the default, 64) traces an N by N grid of rays through each camera. --pixels takes a pixels file: a
list of {"name", "view", "u", "v"} in file pixels (as in landmarks.json).
Each view's crop comes from landmarks.json (needed with --pixels), so u, v are file pixels in and out.
For each ray every surface it passes through is listed in order: object, material, position (mm) and whether it
faces the camera. With --grid the output is compact: per view, tables of object and material names and one row
per ray [u, v, [[object index, material index, x, y, z, faces camera], ...]]. With --pixels each pixel gets a
full listing, traced object by object so surfaces lying on top of each other are all found.
Painted panels are the objects registered with ctx.add(..., panel=True). With --grid every place where one
camera-facing painted surface lies within --stack-mm behind another is a double skin; each panel is traced on
its own, so coincident skins are found too. Without registered panels the double skin count is not given.
Writes <out>/<name>.json (default rays.json; gates.py reads rays*.json). Exit 1 when a double skin is found,
2 on bad input.
"""
import os
import sys

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import kit  # noqa: E402
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, number, save_json, view_sources  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/rays.py -- --out DIR [--project DIR] [--cameras FILE] '
         '[--grid 64 | --pixels PIXELS_FILE] [--stack-mm 10]')


def material_of(ob, idx, dg):
    try:
        ev = ob.evaluated_get(dg)
        mi = ev.data.polygons[idx].material_index
        slot = ev.material_slots[mi] if mi < len(ev.material_slots) else None
        return slot.material.name if slot and slot.material else ''
    except (AttributeError, IndexError):
        return ''


def scene_hits(o, d, step, max_hits, far):
    """Surfaces along a ray, nearest first, with the scene's own ray cast (fast)."""
    sc = B.bpy.context.scene
    dg = B.depsgraph()
    out, start, travelled = [], o.copy(), 0.0
    for _ in range(max_hits):
        hit, loc, nor, idx, ob, _ = sc.ray_cast(dg, start, d, distance=far - travelled)
        if not hit:
            break
        out.append((ob, idx, loc.copy(), nor.dot(d) < 0, (loc - o).length))
        travelled = (loc - o).length + step
        start = loc + d * step
    return out


def object_hits(objs, o, d, step, max_hits, far):
    """Surfaces along a ray traced object by object, so coincident surfaces of two objects are both listed."""
    dg = B.depsgraph()
    hits = []
    for ob in objs:
        inv = ob.matrix_world.inverted()
        lo, ld = inv @ o, inv.to_3x3() @ d
        k = ld.length
        ld.normalize()
        start = lo.copy()
        for _ in range(max_hits):
            ok, loc, nor, idx = ob.ray_cast(start, ld, distance=far * k, depsgraph=dg)
            if not ok:
                break
            wl = ob.matrix_world @ loc
            wn = (inv.transposed().to_3x3() @ nor).normalized()
            hits.append((ob, idx, wl, wn.dot(d) < 0, (wl - o).length))
            start = loc + ld * (step * k)
    hits.sort(key=lambda h: h[4])
    return hits[:max_hits]


class Panels:
    """One BVH per registered painted panel (world space)."""

    def __init__(self, objs):
        self.items = []
        for ob in objs:
            md = B.MeshData(ob)
            if len(md.tris):
                self.items.append((ob.name, BVHTree.FromPolygons([tuple(v) for v in md.verts],
                                                                 [tuple(t) for t in md.tris])))

    def stack(self, o, d, depth, step, far):
        """(position, the two panels, gap) where a second camera-facing panel surface lies within depth behind
        the first camera-facing one, or None."""
        hits = []
        for name, bvh in self.items:
            start, travelled = o.copy(), 0.0
            for _ in range(16):
                loc, nor, idx, dist = bvh.ray_cast(start, d, far - travelled)
                if loc is None:
                    break
                t = (loc - o).length
                hits.append((t, nor.dot(d) < 0, name, loc.copy()))
                travelled = t + step
                start = loc + d * step
        front = sorted(h for h in hits if h[1])
        if len(front) >= 2 and front[1][0] - front[0][0] <= depth:
            return front[0][3], (front[0][2], front[1][2]), front[1][0] - front[0][0]
        return None


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cameras')
    ap.add_argument('--grid', type=int)
    ap.add_argument('--pixels')
    ap.add_argument('--landmarks')
    ap.add_argument('--views')
    ap.add_argument('--stack-mm', type=float, default=10.0)
    ap.add_argument('--step-mm', type=float, default=0.01)
    ap.add_argument('--max-hits', type=int, default=32)
    ap.add_argument('--name', default='rays')
    B.add_project_arg(ap)
    a = ap.parse(argv)
    if a.grid is not None and a.pixels:
        raise BadInput('give --grid or --pixels, not both')
    grid = a.grid if a.grid is not None else (None if a.pixels else 64)
    if grid is not None and not 1 <= grid <= 1024:
        raise BadInput('--grid must be between 1 and 1024')
    if a.stack_mm < 0 or a.step_mm <= 0 or a.max_hits < 1:
        raise BadInput('stack, step and max hits must be positive')
    project = B.project_dir(a)
    cams = F.cameras(load_json(a.cameras or os.path.join(project, 'data', 'cameras.json'), 'cameras file'))
    sources = view_sources(project, a.landmarks, required=bool(a.pixels))
    jobs = {}
    if a.pixels:
        px = F.pixels(load_json(a.pixels, 'pixels file'))
        for e in px:
            if e['view'] not in cams:
                raise BadInput('view %r is not in cameras.json' % e['view'])
            jobs.setdefault(e['view'], []).append((str(e['name']), number(e['u'], 'u'), number(e['v'], 'v')))
    else:
        names = B.globs(a.views) or list(cams)
        for v in names:
            if v not in cams:
                raise BadInput('view %r is not in cameras.json' % v)
            jobs[v] = None
    u = B.mm_per_unit()
    objs = B.visible_geometry()
    if not objs:
        raise BadInput('the scene has no visible geometry')
    lo, hi = B.bbox(objs)
    panels_obs = B.registered('rg_panel')
    panels = Panels(panels_obs) if grid is not None and panels_obs else None
    step, depth = a.step_mm / u, a.stack_mm / u
    res = dict(mode='grid' if grid is not None else 'pixels', grid=grid, stack_mm=a.stack_mm,
               panels=[o.name for o in panels_obs], views={}, places=[], pixels=[])
    doubles = 0
    dg = B.depsgraph()
    for v, todo in jobs.items():
        c = cams[v]
        cam = B.camera_from_view(v, c)
        W, H = int(c['width']), int(c['height'])
        off = ((sources.get(v, (None, None))[1]) or [0, 0])[:2]
        far = float(np.linalg.norm(hi - lo)) * 4 + (cam.matrix_world.translation - Vector((lo + hi) / 2)).length * 2
        undo = kit.steer(float(c['steer_deg']))
        try:
            if todo is None:
                names, mats, rows = [], [], []
                for j in range(grid):
                    for i in range(grid):
                        x, y = (i + 0.5) * W / grid - 0.5, (j + 0.5) * H / grid - 0.5
                        o, d = B.pixel_ray(cam, x, y, W, H)
                        hs = scene_hits(o, d, step, a.max_hits, far)
                        row = []
                        for ob, idx, loc, front, _ in hs:
                            if ob.name not in names:
                                names.append(ob.name)
                            m = material_of(ob, idx, dg)
                            if m not in mats:
                                mats.append(m)
                            row.append([names.index(ob.name), mats.index(m)] + [round(c_ * u, 2) for c_ in loc] +
                                       [bool(front)])
                        rows.append([round(x + off[0], 2), round(y + off[1], 2), row])
                        if panels is not None and hs:
                            st = panels.stack(o, d, depth, step, far)
                            if st:
                                pos, pair, gap = st
                                doubles += 1
                                res['places'].append(dict(view=v, u=x + off[0], v=y + off[1], panels=list(pair),
                                                          position_mm=[c_ * u for c_ in pos], gap_mm=gap * u))
                res['views'][v] = dict(width=W, height=H, objects=names, materials=mats, rays=rows)
                print('VIEW %s: %d rays, %d double skin places so far' % (v, grid * grid, doubles))
            else:
                for name, fu, fv in todo:
                    x, y = fu - off[0], fv - off[1]
                    if not (-0.5 <= x <= W - 0.5 and -0.5 <= y <= H - 0.5):
                        raise BadInput('pixel %g,%g of %r is outside its picture' % (fu, fv, v))
                    o, d = B.pixel_ray(cam, x, y, W, H)
                    hs = object_hits(objs, o, d, step, a.max_hits, far)
                    res['pixels'].append(dict(
                        name=name, view=v, u=fu, v=fv, open=not hs,
                        hits=[dict(object=ob.name, part=ob.get('rg_part', ob.name), material=material_of(ob, idx, dg),
                                   panel=bool(ob.get('rg_panel', False)), position_mm=[c_ * u for c_ in loc],
                                   distance_mm=t * u, faces_camera=bool(front)) for ob, idx, loc, front, t in hs]))
                    print('RAY %s %s %g,%g: %d hits%s' % (name, v, fu, fv, len(hs), '  OPEN' if not hs else ''))
                    for h in res['pixels'][-1]['hits']:
                        print('    %-28s | %-20s | %8.1f mm | %s' % (h['object'], h['material'], h['distance_mm'],
                                                                   'front' if h['faces_camera'] else 'back'))
        finally:
            undo()
    if grid is not None:
        res['double_skins'] = doubles if panels is not None else None
        if panels is None:
            res['note'] = 'no registered painted panels: double skins not looked for'
    else:
        res['double_skins'] = None
    res['passed'] = not doubles
    save_json(os.path.join(a.out, a.name + '.json'), res)
    if grid is not None:
        print('double skins:', res['double_skins'])
    return EXIT_GATE if doubles else EXIT_OK


if __name__ == '__main__':
    B.run(main)
