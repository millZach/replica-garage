"""Render the scene through every solved camera, at each photo's own size.               (runs in Blender)

usage: blender -b <scene.blend> --python tools/render_views.py -- --cameras data/cameras.json --out DIR
       [--mode lit|clay|zebra] [--finish NAME] [--finishes FILE] [--views a,b] [--settings render.json]
       [--scale 1.0] [--engine CYCLES] [--device CPU|GPU] [--gpu-type T] [--samples 64] [--hide globs]

Writes <out>/<view>.png (RGBA, transparent background, so the alpha channel is the render's silhouette) and
<out>/render.json with every setting used. Pass an earlier round's render.json as --settings to render with the
same settings; any setting given on the command line wins and the change is recorded.
Modes: lit (the scene's own lights and materials, with --finish applied), clay (one grey material under a fixed
rig), zebra (a mirror material reflecting a world of 40 stripes; always 40).
Finishes file (default <project>/data/finishes.json, the project being the folder above cameras.json's folder):
  {"finishes": {"<name>": [{"materials": "Paint*", "base_color": [r, g, b], "metallic": 0, "roughness": 0.3,
                            "coat_weight": 1, "coat_roughness": 0.03}]}}
Each render is checked: the Blender camera must project the scene's bounding-box corners within 0.5 px of the
cameras.json model, and the vehicle must be in the picture. Exit 1 when a check fails, 2 on bad input.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, Camera, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/render_views.py -- --cameras data/cameras.json --out DIR '
         '[--mode lit|clay|zebra] [--finish NAME] [--views a,b] [--settings render.json] [--scale 1]')


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--cameras', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--views')
    ap.add_argument('--settings')
    ap.add_argument('--scale', type=float, default=None)
    ap.add_argument('--max-projection-px', type=float, default=0.5)
    B.add_render_args(ap)
    a = ap.parse(argv)
    cams = load_json(a.cameras, 'cameras file').get('cameras')
    if not isinstance(cams, dict) or not cams:
        raise BadInput('%s has no cameras' % a.cameras)
    prior = load_json(a.settings, 'settings file') if a.settings else None
    s, changed = B.render_settings(a, prior)
    scale = a.scale if a.scale is not None else float((prior or {}).get('scale', 1.0))
    if not 0 < scale <= 4:
        raise BadInput('scale must be in (0, 4]')
    views = B.globs(a.views) or list(cams)
    for v in views:
        if v not in cams:
            raise BadInput('view %r is not in %s' % (v, a.cameras))
    project = os.path.dirname(os.path.dirname(os.path.abspath(a.cameras)))
    finishes = B.load_finishes(a.finishes or os.path.join(project, 'data', 'finishes.json'))
    if a.finishes and not os.path.isfile(a.finishes):
        raise BadInput('finishes file not found: %s' % a.finishes)
    hidden = B.hide_objects(B.globs(a.hide) or (prior or {}).get('hide', []))
    geo = B.visible_geometry()
    if not geo:
        raise BadInput('the scene has no visible geometry')
    lo, hi = B.bbox(geo)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    dev = B.setup_render(s)
    look = B.apply_mode(s['mode'], s['finish'], finishes)
    os.makedirs(a.out, exist_ok=True)
    res = dict(s, **dev)
    res.update(look=look, scale=scale, hide=hidden, changed_from_settings=changed, film_transparent=True,
               blender=B.bpy.app.version_string, cameras=os.path.abspath(a.cameras), views={})
    ok = True
    mmu = B.mm_per_unit()
    for v in views:
        c = cams[v]
        cam = B.camera_from_view(v, c, scale)
        model = Camera.from_dict(c)
        W, H = B.bpy.context.scene.render.resolution_x, B.bpy.context.scene.render.resolution_y
        errs = []
        for X in corners:
            if model.depth(X * mmu)[0] <= 0:
                continue
            want = model.project(X * mmu)[0]
            got, _ = B.project_px(cam, X, W, H)
            got = (got + 0.5) / scale - 0.5            # back to photo pixels
            errs.append(float(np.hypot(*(got - want))))
        path = os.path.join(os.path.abspath(a.out), v + '.png')
        B.render_to(path)
        cover = B.alpha_fraction(path)
        perr = max(errs) if errs else None
        checks = dict(projection=perr is not None and perr <= a.max_projection_px, vehicle_in_picture=cover > 0)
        ok &= all(checks.values())
        res['views'][v] = dict(file=path, width=W, height=H, photo_width=int(c['width']),
                               photo_height=int(c['height']), projection_error_px=perr, vehicle_fraction=cover,
                               checks=checks, passed=all(checks.values()))
        print('VIEW %s %dx%d projection %.3f px  vehicle %.1f%%  %s'
              % (v, W, H, perr if perr is not None else -1, 100 * cover, 'pass' if all(checks.values()) else 'FAIL'))
    res['passed'] = bool(ok)
    save_json(os.path.join(a.out, 'render.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
