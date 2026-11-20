"""List every surface a camera ray passes through at given pixels.                        (runs in Blender)

usage: blender -b <scene.blend> --python tools/rays.py -- --camera NAME --pixels "x,y;x,y" --out DIR
       [--cameras data/cameras.json | --closeups closeups.json] [--pixels-file FILE] [--width W --height H]
       [--painted "Paint*"] [--skin-depth-mm 15] [--max-hits 32] [--name rays]

The camera is a view in --cameras (solved photo cameras, at the photo's size), a view in --closeups
(closeups.py), or else a camera object in the scene (at the scene's render size, or --width/--height).
Pixels are in that camera's picture, origin top-left, integer values at pixel centres. --pixels-file holds a
JSON list of [x, y].
For each pixel every surface the ray crosses is listed in order: object, material, position (mm), distance from
the camera (mm), and whether the surface faces the camera. Each object is traced on its own, so surfaces lying
on top of each other (coincident faces of two objects) are all listed. A ray that hits nothing is marked open.
With --painted (material name globs), a pixel has a double skin when a second camera-facing painted surface lies
within --skin-depth-mm behind the first one.
Writes <out>/<name>.json (default rays.json; gates.py reads rays*.json). Exit 1 when --painted is given and any pixel has a double skin,
2 on bad input.
"""
import json
import os
import sys

import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, number, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/rays.py -- --camera NAME --pixels "x,y;x,y" --out DIR '
         '[--cameras data/cameras.json | --closeups closeups.json] [--painted "Paint*"] [--skin-depth-mm 15]')


def parse_pixels(text, path):
    pts = []
    if path:
        d = load_json(path, 'pixels file')
        if not isinstance(d, list):
            raise BadInput('pixels file must hold a list of [x, y]')
        src = d
    else:
        src = []
        for part in (text or '').replace(' ', '').split(';'):
            if part:
                src.append(part.split(','))
    for p in src:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise BadInput('each pixel must be x,y')
        pts.append((number(p[0], 'pixel x'), number(p[1], 'pixel y')))
    if not pts:
        raise BadInput('no pixels given')
    return pts


def get_camera(a):
    sc = B.bpy.context.scene
    if a.cameras:
        cams = load_json(a.cameras, 'cameras file').get('cameras', {})
        if a.camera not in cams:
            raise BadInput('view %r is not in %s' % (a.camera, a.cameras))
        cam = B.camera_from_view(a.camera, cams[a.camera])
        return cam, sc.render.resolution_x, sc.render.resolution_y, 'cameras.json'
    if a.closeups:
        views = {v['name']: v for v in load_json(a.closeups, 'closeups file').get('views', [])}
        if a.camera not in views:
            raise BadInput('view %r is not in %s' % (a.camera, a.closeups))
        v = views[a.camera]
        u = B.mm_per_unit()
        cam = B.look_camera('rg ray ' + a.camera, np.array(v['camera_mm']) / u, np.array(v['centre_mm']) / u,
                            v['up'], v['lens_mm'], v['resolution'])
        cam.data.sensor_width = v.get('sensor_mm', 36.0)
        cam.data.sensor_fit = 'HORIZONTAL'
        return cam, v['resolution'][0], v['resolution'][1], 'closeups.json'
    ob = sc.objects.get(a.camera)
    if ob is None or ob.type != 'CAMERA':
        raise BadInput('no camera object %r in the scene' % a.camera)
    sc.camera = ob
    w = a.width or sc.render.resolution_x * sc.render.resolution_percentage // 100
    h = a.height or sc.render.resolution_y * sc.render.resolution_percentage // 100
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
    return ob, w, h, 'scene'


def trace(objs, o, d, step, max_hits, far):
    dg = B.depsgraph()
    hits = []
    for ob in objs:
        inv = ob.matrix_world.inverted()
        Mi = inv.to_3x3()
        lo, ld = inv @ o, (Mi @ d)
        scale = ld.length
        ld = ld.normalized()
        start = lo.copy()
        ev = ob.evaluated_get(dg)
        for _ in range(max_hits):
            ok, loc, nor, idx = ob.ray_cast(start, ld, distance=far * scale, depsgraph=dg)
            if not ok:
                break
            wl = ob.matrix_world @ loc
            wn = (inv.transposed().to_3x3() @ nor).normalized()
            mat = ''
            try:
                mi = ev.data.polygons[idx].material_index
                slot = ev.material_slots[mi] if mi < len(ev.material_slots) else None
                mat = slot.material.name if slot and slot.material else ''
            except (AttributeError, IndexError):
                pass
            hits.append(dict(object=ob.name, material=mat, loc=wl, dist=(wl - o).length,
                             front=wn.dot(d) < 0, normal=wn))
            start = loc + ld * (step * scale)
    hits.sort(key=lambda h: h['dist'])
    return hits[:max_hits]


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--camera', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--pixels')
    ap.add_argument('--pixels-file')
    ap.add_argument('--cameras')
    ap.add_argument('--closeups')
    ap.add_argument('--width', type=int)
    ap.add_argument('--height', type=int)
    ap.add_argument('--painted', default='')
    ap.add_argument('--skin-depth-mm', type=float, default=15.0)
    ap.add_argument('--step-mm', type=float, default=0.01)
    ap.add_argument('--max-hits', type=int, default=32)
    ap.add_argument('--name', default='rays')
    a = ap.parse(argv)
    if a.cameras and a.closeups:
        raise BadInput('give --cameras or --closeups, not both')
    if a.step_mm <= 0 or a.max_hits < 1 or a.skin_depth_mm < 0:
        raise BadInput('step, max hits and skin depth must be positive')
    pix = parse_pixels(a.pixels, a.pixels_file)
    cam, W, H, source = get_camera(a)
    for x, y in pix:
        if not (-0.5 <= x <= W - 0.5 and -0.5 <= y <= H - 0.5):
            raise BadInput('pixel %g,%g is outside the %dx%d picture' % (x, y, W, H))
    painted = B.globs(a.painted)
    objs = [o for o in B.visible_geometry() if o.type == 'MESH' or o.type in B.GEOMETRY]
    u = B.mm_per_unit()
    lo, hi = B.bbox(objs)
    far = float(np.linalg.norm(hi - lo)) * 10 + (cam.matrix_world.translation - Vector(((lo + hi) / 2))).length * 2
    rows, doubles = [], 0
    for x, y in pix:
        o, d = B.pixel_ray(cam, x, y, W, H)
        hits = trace(objs, o, d, a.step_mm / u, a.max_hits, far)
        dbl = None
        if painted:
            fp = [h for h in hits if h['front'] and B.match(h['material'], painted)]
            dbl = len(fp) >= 2 and (fp[1]['dist'] - fp[0]['dist']) * u <= a.skin_depth_mm
            doubles += int(dbl)
        rows.append(dict(px=[x, y], origin_mm=list(o * u), direction=list(d), open=not hits, double_skin=dbl,
                         hits=[dict(object=h['object'], material=h['material'],
                                    position_mm=[c * u for c in h['loc']], distance_mm=h['dist'] * u,
                                    faces_camera=bool(h['front']), normal=list(h['normal'])) for h in hits]))
        print('RAY %g,%g  %d hits%s%s' % (x, y, len(hits), '  OPEN' if not hits else '',
                                         '  DOUBLE SKIN' if dbl else ''))
        for h in hits:
            print('    %-28s | %-20s | %8.1f mm | %s' % (h['object'], h['material'], h['dist'] * u,
                                                       'front' if h['front'] else 'back'))
    res = dict(camera=a.camera, source=source, width=W, height=H, painted=painted or None,
               skin_depth_mm=a.skin_depth_mm, pixels=rows, double_skins=doubles if painted else None,
               open_pixels=sum(r['open'] for r in rows), passed=not doubles)
    save_json(os.path.join(a.out, a.name + '.json'), json.loads(json.dumps(res, default=float)))
    return EXIT_GATE if doubles else EXIT_OK


if __name__ == '__main__':
    B.run(main)
