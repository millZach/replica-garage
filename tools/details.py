"""Repeatable hero close-ups, cabin cutaway views, strip-light sweeps, A/B toggles and sightlines. (Blender)

usage: blender -b <scene.blend> --python tools/details.py -- --out DIR [--project DIR]
       [--spec data/details.json] [--views a,b] [--look NAME] [--style S] [--sky FILE]
       [--device CPU|GPU] [--gpu-type T] [--samples N] [--resume] [--sightlines]
       [--sightline-tol-mm 5] [--fail-on-occluded] [--no-render]

Reads a list of named detail cameras from --spec (default data/details.json). Each entry defines:
  name, camera_mm [x,y,z], target_mm [x,y,z]; optional up [0,0,1], lens_mm (50), resolution [800, 600],
  lighting ("style" | "studio" | "interior" | "strip-sweep"), hide [part globs hidden for this view only],
  denoise (bool override), toggle_part (part glob for an A/B pair with that part hidden),
  strip_angles_deg (list of azimuth offsets for moving-strip reflection diagnostics),
  targets_mm ({label: [x,y,z]} for ray-based sightline legibility checks from camera_mm).

Writes <out>/<name>.png (plus A/B or strip variants) and <out>/details.json.
Exit 0 on success, 1 when --fail-on-occluded is set and any sightline target is occluded, 2 on bad input.
"""
import math
import os
import re
import sys

import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender as B  # noqa: E402
import _formats as F  # noqa: E402
import kit  # noqa: E402
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, save_json  # noqa: E402

USAGE = ('blender -b <scene.blend> --python tools/details.py -- --out DIR [--project DIR] '
         '[--spec data/details.json] [--views a,b] [--look NAME] [--resume] [--sightlines]')


def _clear_rg_rig():
    """Remove temporary lights, style props and worlds created by a previous lighting mode."""
    sc = B.bpy.context.scene
    for ob in list(sc.objects):
        if ob.get('rg_style') or (ob.type == 'LIGHT' and ob.name.startswith('rg ')):
            B.bpy.data.objects.remove(ob, do_unlink=True)


def _setup_lighting(kind, style, sky, look, finishes, lo, hi, strip_angle_deg=None):
    _clear_rg_rig()
    sc = B.bpy.context.scene
    if kind == 'style':
        info = B.apply_style(style, sky, look, finishes, lo, hi)
        return info
    if kind == 'interior':
        name, _, missing = kit.apply_look(finishes, look) if finishes else (None, 'interior', [])
        rig = kit.build_studio('interior', lo, hi)
        sc.render.film_transparent = False
        return dict(mode='lit', look=name, studio='interior', rig=rig, slots_not_in_scene=missing,
                    color_management=B.apply_color_management(finishes, name))
    if kind == 'strip-sweep':
        name, _, missing = kit.apply_look(finishes, look) if finishes else (None, 'gloss', [])
        for ob in sc.objects:
            if ob.type == 'LIGHT':
                ob.hide_render = True
        c = (np.asarray(lo) + np.asarray(hi)) / 2
        L, W, H = [float(max(v, 1e-3)) for v in (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])]
        kit._world('rg strip sweep', (0.015, 0.015, 0.015), (0.04, 0.04, 0.04), (0.008, 0.008, 0.008))
        ang = math.radians(float(strip_angle_deg or 0.0))
        rad = max(L, W) * 1.4
        pos = (c[0] + math.sin(ang) * rad, c[1] - math.cos(ang) * rad * 0.25, hi[2] + 1.4 * H)
        tgt = (c[0], c[1], lo[2] + 0.45 * H)
        kit._light('rg strip sweep card', 'AREA', 450 * L, pos, tgt, size=L * 1.4, size_y=max(W * 0.08, 0.12))
        sc.render.film_transparent = False
        return dict(mode='lit', look=name, studio='strip-sweep', angle_deg=float(strip_angle_deg or 0.0),
                    slots_not_in_scene=missing, color_management=B.apply_color_management(finishes, name))
    # studio
    return B.apply_mode('lit', look, finishes, lo, hi)


def _snapshot_visibility():
    return {ob.name: (ob.hide_render, ob.hide_viewport) for ob in B.bpy.context.scene.objects}


def _restore_visibility(snap):
    for ob in B.bpy.context.scene.objects:
        if ob.name in snap:
            ob.hide_render, ob.hide_viewport = snap[ob.name]
    B.bpy.context.view_layer.update()


def _check_sightlines(cam_pos, targets_mm, unit, tol_mm):
    """Cast rays from cam_pos (scene units) to each named target point (mm); report visible vs occluded."""
    sc = B.bpy.context.scene
    dg = B.depsgraph()
    out = {}
    ok = True
    for label, pt_mm in targets_mm.items():
        tgt = Vector([float(c) / unit for c in pt_mm])
        vec = tgt - Vector(cam_pos)
        dist = vec.length
        if dist <= 1e-9:
            out[label] = dict(target_mm=list(pt_mm), visible=True, distance_mm=0.0, first_hit=None)
            continue
        hit, loc, _, idx, ob, _ = sc.ray_cast(dg, Vector(cam_pos), vec.normalized(), distance=dist + tol_mm / unit)
        if not hit:
            out[label] = dict(target_mm=list(pt_mm), visible=True, distance_mm=dist * unit,
                              first_hit=None, note='ray reached target without hitting any mesh')
            continue
        hit_dist = (loc - Vector(cam_pos)).length
        shortfall_mm = (dist - hit_dist) * unit
        vis = shortfall_mm <= tol_mm
        ok &= vis
        mat = ''
        try:
            ev = ob.evaluated_get(dg)
            mi = ev.data.polygons[idx].material_index
            slot = ev.material_slots[mi] if mi < len(ev.material_slots) else None
            mat = slot.material.name if slot and slot.material else ''
        except (AttributeError, IndexError):
            pass
        out[label] = dict(target_mm=list(pt_mm), visible=bool(vis), distance_mm=round(dist * unit, 2),
                          hit_distance_mm=round(hit_dist * unit, 2), shortfall_mm=round(shortfall_mm, 2),
                          first_hit=dict(object=ob.name, part=ob.get('rg_part', ob.name), material=mat,
                                         position_mm=[round(c * unit, 2) for c in loc]))
    return out, ok


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--spec')
    ap.add_argument('--views', default='')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--sightlines', action='store_true')
    ap.add_argument('--sightline-tol-mm', type=float, default=5.0)
    ap.add_argument('--fail-on-occluded', action='store_true')
    ap.add_argument('--no-render', action='store_true')
    B.add_project_arg(ap)
    B.add_render_args(ap)
    B.add_style_args(ap)
    a = ap.parse(argv)
    if a.sightline_tol_mm < 0:
        raise BadInput('--sightline-tol-mm must be >= 0')

    project = B.project_dir(a)
    spec_path = a.spec or os.path.join(project, 'data', 'details.json')
    if not os.path.isabs(spec_path):
        spec_path = os.path.join(project, spec_path)
    entries = F.details(load_json(spec_path, 'details file'), os.path.basename(spec_path))
    only = B.globs(a.views)
    if only:
        known = {e['name'] for e in entries}
        for n in only:
            if n not in known:
                raise BadInput('unknown detail view %r' % n)
        entries = [e for e in entries if e['name'] in only]

    finishes = B.load_finishes(project)
    style, sky = B.resolve_style(a, finishes, project, default='showroom')
    settings_path = os.path.join(project, 'data', 'render.json')
    s, ignored, write_to = B.render_settings(a, settings_path)
    if a.no_render:
        write_to = None

    global_hidden = B.hide_objects(B.globs(a.hide))
    geo = B.visible_geometry()
    if not geo:
        raise BadInput('the scene has no visible geometry')
    u = B.mm_per_unit()
    lo, hi = B.bbox(geo)
    dev = B.setup_render(s) if not a.no_render else None
    base_denoise = B.bpy.context.scene.cycles.use_denoising
    os.makedirs(a.out, exist_ok=True)

    rows = []
    all_sightlines_ok = True
    snap_base = _snapshot_visibility()

    for e in entries:
        _restore_visibility(snap_base)
        view_hidden = B.hide_objects(e.get('hide') or [])
        cam_pos = np.asarray(e['camera_mm'], float) / u
        target = np.asarray(e['target_mm'], float) / u
        up = np.asarray(e.get('up') or [0.0, 0.0, 1.0], float)
        lens = float(e.get('lens_mm', 50.0))
        W, H = [int(round(v)) for v in (e.get('resolution') or [800, 600])]
        lighting = e.get('lighting') or ('strip-sweep' if e.get('strip_angles_deg') else 'style')
        if 'denoise' in e and e['denoise'] is not None:
            B.bpy.context.scene.cycles.use_denoising = bool(e['denoise'])
        else:
            B.bpy.context.scene.cycles.use_denoising = base_denoise

        sl_res = None
        if e.get('targets_mm') and (a.sightlines or a.fail_on_occluded or True):
            sl_res, sl_ok = _check_sightlines(cam_pos, e['targets_mm'], u, a.sightline_tol_mm)
            all_sightlines_ok &= sl_ok

        files = []
        look_info = None
        if not a.no_render:
            cam = B.look_camera('rg detail ' + e['name'], cam_pos, target, up, lens, (W, H))
            cam.data.sensor_fit = 'HORIZONTAL'
            angles = e.get('strip_angles_deg')
            if angles:
                for ang in angles:
                    look_info = _setup_lighting('strip-sweep', style, sky, a.look, finishes, lo, hi, ang)
                    tag = ('%+g' % float(ang)).replace('.', 'p')
                    fp = os.path.join(os.path.abspath(a.out), '%s-strip-%s.png' % (e['name'], tag))
                    resumed = a.resume and B.valid_image(fp, (W, H))
                    if not resumed:
                        B.render_to(fp)
                    files.append(dict(variant='strip_%s' % tag, file=fp, resumed=resumed))
            else:
                look_info = _setup_lighting(lighting, style, sky, a.look, finishes, lo, hi)
                fp = os.path.join(os.path.abspath(a.out), e['name'] + '.png')
                resumed = a.resume and B.valid_image(fp, (W, H))
                if not resumed:
                    B.render_to(fp)
                files.append(dict(variant='normal', file=fp, resumed=resumed))
                if e.get('toggle_part'):
                    snap_view = _snapshot_visibility()
                    toggled = B.hide_objects([e['toggle_part']])
                    clean = re.sub(r'[^A-Za-z0-9_-]+', '_', e['toggle_part']).strip('_') or 'part'
                    fp2 = os.path.join(os.path.abspath(a.out), '%s-without-%s.png' % (e['name'], clean))
                    resumed2 = a.resume and B.valid_image(fp2, (W, H))
                    if not resumed2:
                        B.render_to(fp2)
                    files.append(dict(variant='without_' + clean, file=fp2, toggled_objects=toggled, resumed=resumed2))
                    _restore_visibility(snap_view)

        row = dict(name=e['name'], lighting=lighting, camera_mm=list(e['camera_mm']), target_mm=list(e['target_mm']),
                   up=up.tolist(), lens_mm=lens, resolution=[W, H], denoise=B.bpy.context.scene.cycles.use_denoising,
                   hidden=view_hidden, files=files, look=look_info)
        if sl_res is not None:
            row['sightlines'] = sl_res
        rows.append(row)
        print('DETAIL %-24s %s  files=%d%s' % (
            e['name'], lighting, len(files),
            '' if sl_res is None else '  sightlines=%d/%d' % (
                sum(1 for v in sl_res.values() if v['visible']), len(sl_res))))

    _restore_visibility(snap_base)
    if not a.no_render:
        B.write_settings(write_to, s, dev)
    passed = all_sightlines_ok if a.fail_on_occluded else True
    res = dict(spec=os.path.relpath(spec_path, project).replace(os.sep, '/'), global_hidden=global_hidden,
               settings=None if a.no_render else dict(s, **dev), ignored_arguments=ignored,
               views=rows, sightlines_passed=bool(all_sightlines_ok), passed=bool(passed))
    save_json(os.path.join(a.out, 'details.json'), res)
    return EXIT_OK if passed else EXIT_GATE


if __name__ == '__main__':
    B.run(main)
