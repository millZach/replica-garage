"""Put each photo beside its render at the same scale and measure how far apart their silhouettes are.

usage: python tools/compare.py --photos refs/photos --masks refs/masks --renders DIR --out DIR
                               [--cameras data/cameras.json] [--views a,b] [--max-median-px 3] [--max-p95-px 8]
                               [--ref-width 1600] [--panel-width 640] [--no-crop]

For each view it reads the photo <photos>/<view>.*, its mask <masks>/<view>.png (white = vehicle) and the render
<renders>/<view>.png (from render_views.py; its alpha channel is the render's silhouette). It writes
<out>/boards/<view>.jpg (photo, render, and both outlines over the photo, one shared crop so the scale is the
same) and <out>/outline.json with, per view, the median and 95th-percentile distance in px between the two
silhouette edges (measured both ways). Distances are also given scaled to --ref-width image width, and the gate
uses the scaled values. Views default to those in --cameras, else every render found.
Exit 1 when any view is over a limit or its render shows no vehicle, 2 on bad input.
"""
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, find_image, font, load_json, mask_boundary,  # noqa: E402
                     open_image, run, save_json)

USAGE = ('python tools/compare.py --photos refs/photos --masks refs/masks --renders DIR --out DIR '
         '[--cameras data/cameras.json] [--views a,b] [--max-median-px 3] [--max-p95-px 8] [--ref-width 1600]')


def load_mask(path, size, what):
    from PIL import Image
    im = open_image(path, what)
    if im.size != size:
        raise BadInput('%s is %dx%d but the photo is %dx%d' % (what, im.size[0], im.size[1], size[0], size[1]))
    return np.asarray(im.convert('L')) > 127


def render_mask(im, size):
    from PIL import Image
    if 'A' not in im.getbands():
        raise BadInput('render has no alpha channel; render_views.py writes RGBA with a transparent background')
    pw, ph = size
    if abs(im.width / im.height - pw / ph) > 0.01 * pw / ph:
        raise BadInput('render is %dx%d, a different shape from the photo (%dx%d)' % (im.width, im.height, pw, ph))
    if im.size != size:
        im = im.resize(size, Image.Resampling.LANCZOS)
    rgba = np.asarray(im.convert('RGBA'))
    return im, rgba[:, :, 3] > 127


def edge_distances(m1, m2):
    b1, b2 = mask_boundary(m1), mask_boundary(m2)
    if not b1.any() or not b2.any():
        return None
    d2 = ndimage.distance_transform_edt(~b2)
    d1 = ndimage.distance_transform_edt(~b1)
    return np.concatenate([d2[b1], d1[b2]])


def crop_box(m1, m2, aspect, margin=0.08):
    h, w = m1.shape
    ys, xs = np.nonzero(m1 | m2)
    if not len(xs):
        return 0, 0, w, h
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    cw, ch = (x1 - x0) * (1 + 2 * margin), (y1 - y0) * (1 + 2 * margin)
    if cw / ch < aspect:
        cw = ch * aspect
    else:
        ch = cw / aspect
    cw, ch = min(cw, w), min(ch, h)
    mx = np.clip((x0 + x1) / 2, cw / 2, w - cw / 2)
    my = np.clip((y0 + y1) / 2, ch / 2, h - ch / 2)
    return int(round(mx - cw / 2)), int(round(my - ch / 2)), int(round(mx + cw / 2)), int(round(my + ch / 2))


def board(view, photo, rim, pm, rm, stats, out, panel_w, crop):
    from PIL import Image, ImageDraw
    w, h = photo.size
    aspect = w / h
    box = crop_box(pm, rm, aspect) if crop else (0, 0, w, h)
    panel_h = int(round(panel_w * (box[3] - box[1]) / (box[2] - box[0])))
    grey = Image.new('RGBA', rim.size, (128, 128, 126, 255))
    rend = Image.alpha_composite(grey, rim.convert('RGBA')).convert('RGB')
    over = np.asarray(photo.convert('RGB')).copy()
    k = max(1, int(round(w / 800)))
    over[ndimage.binary_dilation(mask_boundary(pm), iterations=k)] = (255, 50, 50)
    over[ndimage.binary_dilation(mask_boundary(rm), iterations=k)] = (40, 220, 255)
    panels = [photo.convert('RGB'), rend, Image.fromarray(over)]
    head = max(28, panel_w // 18)
    gut = 8
    sheet = Image.new('RGB', (3 * panel_w + 4 * gut, panel_h + head + 2 * gut), (236, 236, 233))
    d = ImageDraw.Draw(sheet)
    f = font(max(12, head // 2))
    for i, (p, title) in enumerate(zip(panels, ('photo', 'render', 'outlines: photo red, render blue'))):
        sheet.paste(p.crop(box).resize((panel_w, panel_h), Image.Resampling.LANCZOS),
                    (gut + i * (panel_w + gut), head + gut))
        d.text((gut + i * (panel_w + gut), gut // 2), title, fill=(30, 32, 32), font=f)
    if stats:
        d.text((gut + 2 * (panel_w + gut), gut // 2 + head // 2),
               '%s  median %.1f px  p95 %.1f px (at ref width)' % (view, stats['median_px_ref'], stats['p95_px_ref']),
               fill=(30, 32, 32), font=font(max(10, head // 3)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out, quality=90)


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--photos', required=True)
    ap.add_argument('--masks', required=True)
    ap.add_argument('--renders', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--cameras')
    ap.add_argument('--views')
    ap.add_argument('--max-median-px', type=float, default=3.0)
    ap.add_argument('--max-p95-px', type=float, default=8.0)
    ap.add_argument('--ref-width', type=float, default=1600.0)
    ap.add_argument('--panel-width', type=int, default=640)
    ap.add_argument('--no-crop', action='store_true')
    a = ap.parse(argv)
    for d in (a.photos, a.masks, a.renders):
        if not os.path.isdir(d):
            raise BadInput('folder not found: %s' % d)
    if a.views:
        views = [v.strip() for v in a.views.split(',') if v.strip()]
    elif a.cameras:
        views = list(load_json(a.cameras, 'cameras file').get('cameras', {}))
    else:
        views = sorted(os.path.splitext(n)[0] for n in os.listdir(a.renders) if n.lower().endswith('.png'))
    if not views:
        raise BadInput('no views to compare')
    res = dict(ref_width_px=a.ref_width, max_median_px=a.max_median_px, max_p95_px=a.max_p95_px, views={})
    ok = True
    for v in views:
        pp = find_image(a.photos, v)
        if not pp:
            raise BadInput('no photo for view %r in %s' % (v, a.photos))
        photo = open_image(pp, 'photo %r' % v)
        rp = os.path.join(a.renders, v + '.png')
        rim, rm = render_mask(open_image(rp, 'render %r' % v), photo.size)
        pm = load_mask(os.path.join(a.masks, v + '.png'), photo.size, 'mask %r' % v)
        if not pm.any():
            raise BadInput('mask %r is empty' % v)
        d = edge_distances(pm, rm)
        scale = a.ref_width / photo.width
        if d is None:
            st = dict(median_px=None, p95_px=None, median_px_ref=float('inf'), p95_px_ref=float('inf'),
                      note='the render shows no vehicle', passed=False)
        else:
            med, p95 = float(np.median(d)), float(np.percentile(d, 95))
            st = dict(median_px=med, p95_px=p95, max_px=float(d.max()), median_px_ref=med * scale,
                      p95_px_ref=p95 * scale, edge_pixels=int(len(d)),
                      area_ratio=float(rm.sum() / pm.sum()))
            st['passed'] = st['median_px_ref'] <= a.max_median_px and st['p95_px_ref'] <= a.max_p95_px
        st.update(photo=pp, render=rp, width=photo.width, height=photo.height,
                  board=os.path.join(a.out, 'boards', v + '.jpg'))
        board(v, photo, rim, pm, rm, st if d is not None else None, st['board'], a.panel_width, not a.no_crop)
        ok &= st['passed']
        res['views'][v] = st
        print('%-16s median %6.2f px  p95 %6.2f px (at %d px width)  %s'
              % (v, st['median_px_ref'], st['p95_px_ref'], a.ref_width, 'pass' if st['passed'] else 'FAIL'))
    res['passed'] = bool(ok)
    save_json(os.path.join(a.out, 'outline.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
