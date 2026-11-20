"""Put each view's picture beside its render at the same scale and measure how far apart the silhouettes are.

usage: python tools/compare.py --renders DIR --out DIR [--project DIR] [--cameras data/cameras.json]
                               [--masks refs/masks] [--views a,b] [--max-median-px N] [--max-p95-px N]
                               [--ref-width N] [--panel-width 640] [--no-crop]

For each view in cameras.json: the picture is its file cut to its crop, the mask is <masks>/<view>.png (white =
vehicle, from mask_photo.py) and the render is <renders>/<view>.png (from render_views.py; any size of the same
shape; its alpha channel is the render's silhouette). Writes <out>/boards/<view>.jpg (picture, render, and both
outlines over the picture, one shared crop so the scale is the same) and <out>/outline.json: per view the median
and 95th-percentile distance between the two silhouette edges (measured both ways), in px and scaled to a
--ref-width wide image. Limits default to data/limits.json, else tools/default_limits.json.
Only precise views count toward the gate; visual views get boards and numbers but are not judged. A precise view
with no mask or no vehicle in its render fails.
Exit 1 when a counted view is over a limit, 2 on bad input.
"""
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, font, load_json, mask_boundary, open_image,  # noqa: E402
                     project_limits, run, save_json, view_picture)

USAGE = ('python tools/compare.py --renders DIR --out DIR [--project DIR] [--cameras data/cameras.json] '
         '[--masks refs/masks] [--views a,b] [--max-median-px N] [--max-p95-px N] [--ref-width N]')


def render_mask(im, size):
    from PIL import Image
    if 'A' not in im.getbands():
        raise BadInput('render has no alpha channel; render_views.py writes RGBA with a transparent background')
    pw, ph = size
    if abs(im.width / im.height - pw / ph) > 0.01 * pw / ph:
        raise BadInput('render is %dx%d, a different shape from the picture (%dx%d)' % (im.width, im.height, pw, ph))
    if im.size != size:
        im = im.resize(size, Image.Resampling.LANCZOS)
    return im, np.asarray(im.convert('RGBA'))[:, :, 3] > 127


def edge_distances(m1, m2):
    b1, b2 = mask_boundary(m1), mask_boundary(m2)
    if not b1.any() or not b2.any():
        return None
    return np.concatenate([ndimage.distance_transform_edt(~b2)[b1], ndimage.distance_transform_edt(~b1)[b2]])


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


def board(view, pic, rim, pm, rm, line, out, panel_w, crop):
    from PIL import Image, ImageDraw
    w, h = pic.size
    box = crop_box(pm if pm is not None else rm, rm, w / h) if crop else (0, 0, w, h)
    panel_h = max(1, int(round(panel_w * (box[3] - box[1]) / max(1, box[2] - box[0]))))
    grey = Image.new('RGBA', rim.size, (128, 128, 126, 255))
    rend = Image.alpha_composite(grey, rim.convert('RGBA')).convert('RGB')
    over = np.asarray(pic.convert('RGB')).copy()
    k = max(1, int(round(w / 800)))
    if pm is not None:
        over[ndimage.binary_dilation(mask_boundary(pm), iterations=k)] = (255, 50, 50)
    over[ndimage.binary_dilation(mask_boundary(rm), iterations=k)] = (40, 220, 255)
    head = max(28, panel_w // 18)
    gut = 8
    sheet = Image.new('RGB', (3 * panel_w + 4 * gut, panel_h + head + 2 * gut), (236, 236, 233))
    d = ImageDraw.Draw(sheet)
    f = font(max(12, head // 2))
    for i, (p, title) in enumerate(zip((pic.convert('RGB'), rend, Image.fromarray(over)),
                                       ('picture', 'render', 'outlines: picture red, render blue'))):
        sheet.paste(p.crop(box).resize((panel_w, panel_h), Image.Resampling.LANCZOS), (gut + i * (panel_w + gut),
                                                                                      head + gut))
        d.text((gut + i * (panel_w + gut), gut // 2), title, fill=(30, 32, 32), font=f)
    d.text((gut + 2 * (panel_w + gut), gut // 2 + head // 2), view + '  ' + line, fill=(30, 32, 32),
           font=font(max(10, head // 3)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out, quality=90)


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('--renders', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--project', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--cameras')
    ap.add_argument('--masks')
    ap.add_argument('--views')
    ap.add_argument('--max-median-px', type=float)
    ap.add_argument('--max-p95-px', type=float)
    ap.add_argument('--ref-width', type=float)
    ap.add_argument('--panel-width', type=int, default=640)
    ap.add_argument('--no-crop', action='store_true')
    a = ap.parse(argv)
    project = os.path.abspath(a.project)
    lim, _ = project_limits(project)
    med_lim = a.max_median_px if a.max_median_px is not None else lim['outline_median_px']
    p95_lim = a.max_p95_px if a.max_p95_px is not None else lim['outline_p95_px']
    ref = a.ref_width if a.ref_width is not None else lim['outline_ref_width_px']
    cams = load_json(a.cameras or os.path.join(project, 'data', 'cameras.json'), 'cameras file').get('cameras')
    if not isinstance(cams, dict) or not cams:
        raise BadInput('cameras.json has no cameras')
    masks = a.masks or os.path.join(project, 'refs', 'masks')
    if not os.path.isdir(a.renders):
        raise BadInput('renders folder not found: %s' % a.renders)
    views = [v.strip() for v in a.views.split(',') if v.strip()] if a.views else list(cams)
    res = dict(ref_width_px=ref, max_median_px=med_lim, max_p95_px=p95_lim, views={})
    ok = True
    for v in views:
        if v not in cams:
            raise BadInput('view %r is not in cameras.json' % v)
        c = cams[v]
        counted = c.get('grade') == 'precise'
        if not c.get('file'):
            raise BadInput('camera %r has no file' % v)
        pic, _ = view_picture(project, c['file'], c.get('crop'), 'picture of %r' % v)
        if pic.size != (int(c['width']), int(c['height'])):
            raise BadInput('picture of %r is %dx%d but its camera is %dx%d' % (v, pic.width, pic.height,
                                                                                c['width'], c['height']))
        rp = os.path.join(a.renders, v + '.png')
        rim, rm = render_mask(open_image(rp, 'render of %r' % v), pic.size)
        mp = os.path.join(masks, v + '.png')
        pm = None
        if os.path.isfile(mp):
            mim = open_image(mp, 'mask of %r' % v)
            if mim.size != pic.size:
                raise BadInput('mask of %r is %dx%d, the picture %dx%d' % (v, mim.width, mim.height, *pic.size))
            pm = np.asarray(mim.convert('L')) > 127
        st = dict(grade=c.get('grade'), counted=counted, width=pic.width, height=pic.height, render=rp,
                  mask=mp if pm is not None else None, board=os.path.join(a.out, 'boards', v + '.jpg'))
        d = edge_distances(pm, rm) if pm is not None and pm.any() else None
        if d is None:
            st.update(median_px=None, p95_px=None, median_px_ref=None, p95_px_ref=None,
                      note='no mask for this view' if pm is None or not pm.any() else 'the render shows no vehicle')
            st['passed'] = False if counted else None
            line = st['note']
        else:
            k = ref / pic.width
            med, p95 = float(np.median(d)), float(np.percentile(d, 95))
            st.update(median_px=med, p95_px=p95, max_px=float(d.max()), median_px_ref=med * k, p95_px_ref=p95 * k,
                      edge_pixels=int(len(d)), area_ratio=float(rm.sum() / max(1, pm.sum())))
            within = st['median_px_ref'] <= med_lim and st['p95_px_ref'] <= p95_lim
            st['passed'] = within if counted else None
            line = 'median %.1f px  p95 %.1f px at %g px width%s' % (st['median_px_ref'], st['p95_px_ref'], ref,
                                                                   '' if counted else '  (visual: not counted)')
        board(v, pic, rim, pm, rm, line, st['board'], a.panel_width, not a.no_crop)
        if counted:
            ok &= bool(st['passed'])
        res['views'][v] = st
        print('%-16s %-8s %s  %s' % (v, c.get('grade'), line, '' if not counted else
                                     ('pass' if st['passed'] else 'FAIL')))
    res['passed'] = bool(ok)
    save_json(os.path.join(a.out, 'outline.json'), res)
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
