"""Render the scene through every solved camera, at each picture's own size and steering angle. (Blender)

usage: blender -b <scene.blend> --python tools/render_views.py -- --mode lit|clay|zebra --out DIR
       [--project DIR] [--cameras data/cameras.json] [--look NAME] [--view NAME] [--trial]
       [--device CPU|GPU] [--gpu-type T] [--samples N] [--hide parts]

Writes <out>/<view>.png (RGBA, transparent background, so the alpha channel is the render's silhouette) and
<out>/render_views.json. Modes: lit is the look (--look, default the proof look in data/finishes.json) under
its studio preset (kit.py); clay is plain grey, to show shape without paint; zebra mirrors 40 stripes in the
paint, to show ripples. Each view's steer_deg turns the steerable front wheels for that render.
An evidence run (no --trial) takes its sampling and device from data/render.json; the first one writes it, so
every round matches. --trial is for builders: half size, few samples, and data/render.json is neither read nor
written.
Each render is checked: the Blender camera must put the scene's bounding-box corners within 0.5 px of the
cameras.json model, and the vehicle must be in the picture. Exit 1 when a check fails, 2 on bad input.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import kit  # noqa: E402
import _formats as F  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, Camera, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/render_views.py -- --mode lit|clay|zebra --out DIR '
         '[--project DIR] [--look NAME] [--view NAME] [--trial]')


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cameras')
    ap.add_argument('--view')
    ap.add_argument('--trial', action='store_true')
    ap.add_argument('--resume', action='store_true', help='skip views whose output PNG already exists at the right size')
    ap.add_argument('--max-projection-px', type=float, default=0.5)
    B.add_project_arg(ap)
    B.add_render_args(ap)
    a = ap.parse(argv)
    if not a.mode:
        raise BadInput('--mode lit, clay or zebra is needed')
    project = B.project_dir(a)
    cams = F.cameras(load_json(a.cameras or os.path.join(project, 'data', 'cameras.json'), 'cameras file'))
    views = [a.view] if a.view else list(cams)
    if a.view and a.view not in cams:
        raise BadInput('view %r is not in cameras.json' % a.view)
    settings_path = os.path.join(project, 'data', 'render.json')
    s, ignored, write_to = B.render_settings(a, settings_path, a.trial)
    scale = 0.5 if a.trial else 1.0
    finishes = B.load_finishes(project)
    hidden = B.hide_objects(B.globs(a.hide))
    geo = B.visible_geometry()
    if not geo:
        raise BadInput('the scene has no visible geometry')
    lo, hi = B.bbox(geo)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    dev = B.setup_render(s)
    look = B.apply_mode(a.mode, a.look, finishes, lo, hi)
    os.makedirs(a.out, exist_ok=True)
    res = dict(mode=a.mode, trial=a.trial, scale=scale, settings=dict(s, **dev), settings_file=None if a.trial
               else settings_path, ignored_arguments=ignored, look=look, hidden=hidden,
               blender=B.bpy.app.version_string, views={})
    ok = True
    mmu = B.mm_per_unit()
    for v in views:
        c = cams[v]
        cam = B.camera_from_view(v, c, scale)
        model = Camera.from_dict(c)
        W, H = B.bpy.context.scene.render.resolution_x, B.bpy.context.scene.render.resolution_y
        sx, sy = W / float(c['width']), H / float(c['height'])
        undo = kit.steer(float(c['steer_deg']))
        resumed = False
        try:
            errs = []
            for X in corners:
                if model.kind == 'perspective' and model.depth(X * mmu)[0] <= 0:
                    continue
                want = model.project(X * mmu)[0]
                got, _ = B.project_px(cam, X, W, H)
                got = np.array([(got[0] + 0.5) / sx - 0.5, (got[1] + 0.5) / sy - 0.5])  # back to picture pixels
                errs.append(float(np.hypot(*(got - want))))
            path = os.path.join(os.path.abspath(a.out), v + '.png')
            if a.resume and B.valid_image(path, (W, H)):
                resumed = True
            else:
                B.render_to(path)
        finally:
            undo()
        cover = B.alpha_fraction(path)
        perr = max(errs) if errs else None
        checks = dict(projection=perr is not None and perr <= a.max_projection_px, vehicle_in_picture=cover > 0)
        ok &= all(checks.values())
        res['views'][v] = dict(file=path, width=W, height=H, kind=c.get('kind', 'perspective'),
                               steer_deg=c.get('steer_deg', 0), grade=c.get('grade'), projection_error_px=perr,
                               vehicle_fraction=cover, resumed=resumed, checks=checks, passed=all(checks.values()))
        print('VIEW %s %dx%d projection %.3f px  vehicle %.1f%%  %s%s'
              % (v, W, H, perr if perr is not None else -1, 100 * cover,
                 'pass' if all(checks.values()) else 'FAIL', ' (resumed)' if resumed else ''))
    B.write_settings(write_to, s, dev)
    res['passed'] = bool(ok)
    save_json(os.path.join(a.out, 'render_views.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
