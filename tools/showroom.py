"""Save a ready-to-open showroom .blend (with look, colour management, lights and camera) and handoff JSON. (Blender)

usage: blender -b <scene.blend> --python tools/showroom.py -- [--project DIR] [--out FILE]
       [--look NAME] [--style showroom|studio|daylight] [--sky FILE] [--camera front-left]
       [--lens 85] [--height-mm 900] [--fill 0.85] [--resolution 1920x1080] [--handoff FILE]

Opens an assembled vehicle.blend, applies the chosen look, colour management and presentation style, places a
long-lens framing camera aimed at the vehicle, configures Cycles, and saves a ready-to-open .blend (default
out/vehicle-showroom.blend). Optionally writes a handoff JSON (--handoff, e.g. data/handoff.json) listing the
model paths, look, colour management, style, assemblies, steerable parts, emissive slots and registered parts so
downstream rendering or video tools can load and animate the vehicle cleanly.
Exit 0 on success, 2 on bad input.
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import kit  # noqa: E402
import orbit  # noqa: E402
from _common import ArgParser, BadInput, EXIT_OK, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/showroom.py -- [--project DIR] [--out FILE] '
         '[--look NAME] [--style showroom|studio|daylight] [--camera front-left] [--handoff FILE]')


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out')
    ap.add_argument('--camera', default='front-left')
    ap.add_argument('--lens', type=float, default=85.0)
    ap.add_argument('--height-mm', type=float, default=900.0)
    ap.add_argument('--fill', type=float, default=0.85)
    ap.add_argument('--resolution', default='1920x1080')
    ap.add_argument('--handoff')
    B.add_project_arg(ap)
    B.add_render_args(ap)
    B.add_style_args(ap)
    a = ap.parse(argv)

    valid_cams = orbit.RING + tuple(name for name, _ in orbit.ABOVE)
    if a.camera not in valid_cams:
        raise BadInput('unknown camera %r (choices: %s)' % (a.camera, ', '.join(valid_cams)))
    if a.lens <= 0 or not 0.2 <= a.fill <= 1.2 or a.height_mm <= 0:
        raise BadInput('lens, fill or height out of range')
    try:
        W, H = [int(v) for v in a.resolution.lower().split('x')]
    except ValueError:
        raise BadInput('--resolution must look like 1920x1080')
    if W < 8 or H < 8:
        raise BadInput('--resolution is too small')

    project = B.project_dir(a)
    finishes = B.load_finishes(project)
    style, sky = B.resolve_style(a, finishes, project, default='showroom')
    geo = B.visible_geometry()
    if not geo:
        raise BadInput('the scene has no visible geometry')
    u = B.mm_per_unit()
    lo, hi = B.bbox(geo)
    corners = B.framing_corners(geo)
    target = (lo + hi) / 2
    tx = 18.0 / a.lens
    ty = tx * H / W
    if a.camera in orbit.RING:
        cam_pos = orbit.place(orbit.heading(a.camera), target, corners, tx, ty, a.fill, a.height_mm / u)
    else:
        base = dict(orbit.ABOVE)[a.camera]
        e = math.radians(40.0)
        d = orbit.heading(base) * math.cos(e) + np.array([0, 0, math.sin(e)])
        cam_pos = orbit.place(d, target, corners, tx, ty, a.fill, None)

    look_info = B.apply_style(style, sky, a.look, finishes, lo, hi)
    cam = B.look_camera('rg showroom camera', cam_pos, target, (0, 0, 1), a.lens, (W, H))
    cam.data.sensor_fit = 'HORIZONTAL'
    sc = B.bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.render.film_transparent = False

    src_blend = os.path.abspath(B.bpy.data.filepath) if B.bpy.data.filepath else None
    out = os.path.abspath(a.out or os.path.join(project, 'out', 'vehicle-showroom.blend'))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    B.bpy.ops.wm.save_as_mainfile(filepath=out)

    # Inventory dynamic hooks (steerable wheels, emissive slots, interfaces, assemblies) for downstream tools
    steerable = {ob.name: ob.get('rg_steer') for ob in geo if ob.get('rg_steer')}
    emissive_slots = []
    if finishes and look_info.get('look'):
        slots = finishes['looks'][look_info['look']].get('slots', {})
        emissive_slots = sorted(k for k, v in slots.items() if float(v.get('emission_strength', 0) or 0) > 0)
    build_meta = json.loads(sc['rg_build']) if sc.get('rg_build') else []
    interfaces = sorted(json.loads(sc['rg_interfaces']).keys()) if sc.get('rg_interfaces') else []
    summary = dict(
        source_blend=src_blend,
        showroom_blend=out,
        look=look_info.get('look'),
        style=style,
        color_management=look_info.get('color_management'),
        camera=dict(name=a.camera, camera_mm=(cam_pos * u).tolist(), target_mm=(target * u).tolist(),
                    lens_mm=a.lens, resolution=[W, H]),
        assemblies=build_meta,
        object_count=len(geo),
        steerable=steerable,
        emissive_slots=emissive_slots,
        interfaces=interfaces,
        passed=os.path.isfile(out),
    )
    save_json(out + '.json', summary)
    if a.handoff:
        hp = a.handoff if os.path.isabs(a.handoff) else os.path.join(project, a.handoff)
        save_json(hp, summary)
    print('SHOWROOM', out)
    return EXIT_OK


if __name__ == '__main__':
    B.run(main)
