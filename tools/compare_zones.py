"""Compose a 1:1 Hero Zone Comparison Sheet placing reference and render side-by-side at matching scale.

usage: python tools/compare_zones.py --renders DIR --out DIR [--project DIR] [--zones data/zones.json]
       [--landmarks data/landmarks.json] [--cameras data/cameras.json] [--masks refs/masks]
       [--panel-width 720] [--sheet-name hero-zones.jpg] [--save-crops]

Produces one contact sheet (<out>/<sheet-name>, default hero-zones.jpg) and <out>/compare_zones.json
comparing 5 hero exterior zones at matching 1:1 scale:
  (a) Front headlamps & nose
  (b) Rear hatch glass & tail lamps
  (c) Roofline / B-pillar / quarter window
  (d) Rear quarter-to-bumper seam
  (e) Full side profile

Zone crops can be configured per vehicle in data/zones.json (or --zones FILE), using either exact
pixel coordinates ("box_px": [u0, v0, u1, v1]), vehicle-silhouette-relative coordinates
("box_norm": [x0, y0, x1, y1] in 0..1 of the vehicle bounding box), or full-image-relative
coordinates ("box_img_norm": [x0, y0, x1, y1]). When no zones file is given, clear defaults are
applied to matching solved views from landmarks.json / --renders.

Exit 0 on success, 2 on bad input.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _formats as F  # noqa: E402
from _common import (ArgParser, BadInput, EXIT_OK, find_image, font, load_json, open_image, run,  # noqa: E402
                     save_json, view_picture, view_sources)

USAGE = ('python tools/compare_zones.py --renders DIR --out DIR [--project DIR] '
         '[--zones data/zones.json] [--landmarks data/landmarks.json] [--panel-width 720]')

DEFAULT_ZONES = (
    {
        'id': 'front_headlamps_nose',
        'label': '(a) Front headlamps & nose',
        'view_candidates': ('front', 'front-34', 'front-left', 'front-right'),
        'box_norm': [0.02, 0.25, 0.98, 0.88],
    },
    {
        'id': 'rear_hatch_tails',
        'label': '(b) Rear hatch glass & tail lamps',
        'view_candidates': ('rear', 'rear-34', 'rear-right', 'rear-left'),
        'box_norm': [0.02, 0.10, 0.98, 0.72],
    },
    {
        'id': 'roofline_greenhouse',
        'label': '(c) Roofline / B-pillar / quarter window',
        'view_candidates': ('side', 'left', 'right', 'side-left', 'side-right'),
        'box_norm': [0.22, 0.00, 0.85, 0.56],
    },
    {
        'id': 'rear_quarter_bumper',
        'label': '(d) Rear quarter-to-bumper seam',
        'view_candidates': ('rear-right', 'rear-34', 'rear-left', 'side', 'left', 'rear'),
        'box_norm': [0.55, 0.22, 1.02, 0.86],
    },
    {
        'id': 'side_profile',
        'label': '(e) Full side profile',
        'view_candidates': ('side', 'left', 'right', 'side-left', 'side-right'),
        'box_norm': [-0.04, -0.06, 1.04, 1.06],
    },
)


def _silhouette_bbox(im, mask_path=None):
    """Return (x0, y0, x1, y1) of the vehicle silhouette from mask_path or RGBA alpha, else full image."""
    w, h = im.size
    m = None
    if mask_path and os.path.isfile(mask_path):
        mim = open_image(mask_path, 'mask')
        if mim.size == im.size:
            m = np.asarray(mim.convert('L')) > 127
    if m is None and 'A' in im.getbands():
        m = np.asarray(im.convert('RGBA'))[:, :, 3] > 127
    if m is not None and m.any():
        ys, xs = np.nonzero(m)
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    return 0, 0, w, h


def _clamp_box(x0, y0, x1, y1, w, h):
    x0 = max(0, min(w - 1, int(round(x0))))
    y0 = max(0, min(h - 1, int(round(y0))))
    x1 = max(x0 + 1, min(w, int(round(x1))))
    y1 = max(y0 + 1, min(h, int(round(y1))))
    return x0, y0, x1, y1


def resolve_crop(zone, size, bbox):
    """Resolve pixel crop box (u0, v0, u1, v1) inside an image of `size`=(w, h) with vehicle `bbox`."""
    w, h = size
    if zone.get('box_px') is not None:
        u0, v0, u1, v1 = [float(c) for c in zone['box_px']]
        return _clamp_box(u0, v0, u1, v1, w, h)
    if zone.get('box_img_norm') is not None:
        nx0, ny0, nx1, ny1 = [float(c) for c in zone['box_img_norm']]
        return _clamp_box(nx0 * w, ny0 * h, nx1 * w, ny1 * h, w, h)
    nx0, ny0, nx1, ny1 = [float(c) for c in zone.get('box_norm', [0.0, 0.0, 1.0, 1.0])]
    bx0, by0, bx1, by1 = bbox
    bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
    return _clamp_box(bx0 + nx0 * bw, by0 + ny0 * bh, bx0 + nx1 * bw, by0 + ny1 * bh, w, h)


def _pick_view(zone, available):
    if zone.get('view'):
        return zone['view']
    avail_lower = {v.lower(): v for v in available}
    for cand in zone.get('view_candidates', ()):
        if cand in available:
            return cand
        if cand.lower() in avail_lower:
            return avail_lower[cand.lower()]
    for cand in zone.get('view_candidates', ()):
        for v in available:
            if cand.lower() in v.lower():
                return v
    return available[0] if available else None


def _composite_render(rim):
    from PIL import Image
    if 'A' in rim.getbands():
        grey = Image.new('RGBA', rim.size, (128, 128, 126, 255))
        return Image.alpha_composite(grey, rim.convert('RGBA')).convert('RGB')
    return rim.convert('RGB')


def compose_zone_sheet(entries, out_path, panel_w=720, title='1:1 Hero Zone Comparison (Reference | Render)'):
    """Compose all cropped (ref, render) zone pairs into one vertical contact sheet."""
    from PIL import Image, ImageDraw

    gut = 10
    row_head = max(26, panel_w // 24)
    top_head = max(36, panel_w // 16)
    sheet_w = 2 * panel_w + 3 * gut

    scaled = []
    total_h = top_head + gut
    for e in entries:
        ref_crop = e['ref_crop']
        rend_crop = e['render_crop']
        cw, ch = ref_crop.size
        panel_h = max(1, int(round(panel_w * ch / max(1, cw))))
        r_im = ref_crop.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
        d_im = rend_crop.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
        scaled.append((e, r_im, d_im, panel_h))
        total_h += row_head + panel_h + gut

    sheet = Image.new('RGB', (sheet_w, total_h), (28, 30, 34))
    draw = ImageDraw.Draw(sheet)
    title_font = font(max(15, top_head // 2))
    row_font = font(max(12, row_head // 2))
    sub_font = font(max(10, row_head // 2 - 2))

    draw.text((gut, gut // 2), title, fill=(238, 240, 244), font=title_font)
    draw.text((gut, top_head - row_head // 2), 'REFERENCE', fill=(170, 200, 255), font=sub_font)
    draw.text((2 * gut + panel_w, top_head - row_head // 2), 'RENDER (1:1 MATCHING SCALE)',
              fill=(170, 240, 195), font=sub_font)

    y = top_head + gut
    for e, r_im, d_im, panel_h in scaled:
        header = '%s   [%s  crop %dx%d px]' % (e['label'], e['view'] or 'custom', e['crop_size'][0],
                                               e['crop_size'][1])
        draw.rectangle([gut, y, sheet_w - gut, y + row_head - 2], fill=(44, 48, 56))
        draw.text((gut + 6, y + max(2, (row_head - 16) // 2)), header, fill=(235, 237, 240), font=row_font)
        y += row_head
        sheet.paste(r_im, (gut, y))
        sheet.paste(d_im, (2 * gut + panel_w, y))
        y += panel_h + gut

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path, quality=92)
    return sheet.size


def main(argv):
    from PIL import Image

    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--renders', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--project', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--zones', default=None)
    ap.add_argument('--landmarks', default=None)
    ap.add_argument('--cameras', default=None)
    ap.add_argument('--masks', default=None)
    ap.add_argument('--panel-width', type=int, default=720)
    ap.add_argument('--sheet-name', default='hero-zones.jpg')
    ap.add_argument('--save-crops', action='store_true')
    a = ap.parse(argv)

    if a.panel_width < 64:
        raise BadInput('--panel-width must be at least 64')
    project = os.path.abspath(a.project)
    if not os.path.isdir(a.renders):
        raise BadInput('renders folder not found: %s' % a.renders)

    sources = view_sources(project, a.landmarks, required=False)
    masks_dir = a.masks or os.path.join(project, 'refs', 'masks')

    zones_path = a.zones or os.path.join(project, 'data', 'zones.json')
    if a.zones or os.path.isfile(zones_path):
        zone_specs = F.zones(load_json(zones_path, 'zones file'), os.path.basename(zones_path))
    else:
        zone_specs = [dict(z) for z in DEFAULT_ZONES]

    available_views = [v for v in sources if find_image(a.renders, v) is not None]
    if not available_views and any(not (z.get('ref') and z.get('render')) for z in zone_specs):
        raise BadInput('no matching view renders found in %s for views in landmarks.json' % a.renders)

    entries = []
    meta_rows = []
    for z in zone_specs:
        view = None
        if z.get('ref') and z.get('render'):
            ref_path = z['ref'] if os.path.isabs(z['ref']) else os.path.join(project, z['ref'])
            rend_path = z['render'] if os.path.isabs(z['render']) else os.path.join(project, z['render'])
            pic = open_image(ref_path, 'reference of zone %r' % z['id'])
            rim = open_image(rend_path, 'render of zone %r' % z['id'])
            view = z.get('view') or z['id']
            mask_path = None
        else:
            view = _pick_view(z, available_views)
            if not view or view not in sources:
                raise BadInput('zone %r: view %r not found in landmarks.json' % (z['id'], view))
            rend_path = find_image(a.renders, view)
            if rend_path is None:
                raise BadInput('zone %r: render for view %r not found in %s' % (z['id'], view, a.renders))
            pic, _ = view_picture(project, sources[view][0], sources[view][1], 'picture of %r' % view)
            rim = open_image(rend_path, 'render of %r' % view)
            ref_path = sources[view][0]
            mask_path = os.path.join(masks_dir, view + '.png')

        # Resize render to reference dimensions when same-camera or proportional so both share 1:1 pixel space
        same_camera = not (z.get('ref') and z.get('render')) or (
            abs(rim.width / max(1, rim.height) - pic.width / max(1, pic.height)) <= 0.02 * (pic.width / max(1, pic.height))
        )
        if same_camera:
            if rim.size != pic.size:
                rim_aligned = rim.resize(pic.size, Image.Resampling.LANCZOS)
            else:
                rim_aligned = rim
            bbox = _silhouette_bbox(rim_aligned, mask_path=mask_path)
            crop = resolve_crop(z, pic.size, bbox)
            ref_crop = pic.convert('RGB').crop(crop)
            rend_crop = _composite_render(rim_aligned).crop(crop)
            render_crop_box = crop
        else:
            ref_bbox = _silhouette_bbox(pic, mask_path=mask_path)
            rend_bbox = _silhouette_bbox(rim, mask_path=None)
            crop = resolve_crop(z, pic.size, ref_bbox)
            render_crop_box = resolve_crop(z, rim.size, rend_bbox)
            ref_crop = pic.convert('RGB').crop(crop)
            rend_crop = _composite_render(rim).crop(render_crop_box)

        crop_files = None
        if a.save_crops:
            cdir = os.path.join(a.out, 'zones')
            os.makedirs(cdir, exist_ok=True)
            rf = os.path.join(cdir, z['id'] + '-ref.jpg')
            df = os.path.join(cdir, z['id'] + '-render.jpg')
            ref_crop.save(rf, quality=92)
            rend_crop.save(df, quality=92)
            crop_files = dict(ref=rf, render=df)

        entries.append(dict(
            id=z['id'],
            label=z.get('label', z['id']),
            view=view,
            ref_crop=ref_crop,
            render_crop=rend_crop,
            crop_size=[crop[2] - crop[0], crop[3] - crop[1]],
        ))
        meta_rows.append(dict(
            id=z['id'],
            label=z.get('label', z['id']),
            view=view,
            ref=ref_path,
            render=rend_path,
            ref_crop_px=list(crop),
            render_crop_px=list(render_crop_box),
            same_camera_scale=bool(same_camera),
            crops=crop_files,
        ))

    sheet_path = os.path.join(a.out, a.sheet_name)
    sheet_size = compose_zone_sheet(entries, sheet_path, panel_w=a.panel_width)
    out = dict(
        sheet=sheet_path,
        sheet_size=list(sheet_size),
        panel_width=int(a.panel_width),
        zones_file=zones_path if (a.zones or os.path.isfile(zones_path)) else None,
        zones=meta_rows,
        passed=True,
    )
    save_json(os.path.join(a.out, 'compare_zones.json'), out)
    print('ZONES SHEET %s (%dx%d, %d zones)' % (sheet_path, sheet_size[0], sheet_size[1], len(meta_rows)))
    return EXIT_OK


if __name__ == '__main__':
    run(main)
