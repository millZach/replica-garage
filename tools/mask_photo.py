"""Make the silhouette mask of one view from landmarks.json.

usage: python tools/mask_photo.py <view> [--project DIR] [--landmarks FILE] [--seed RENDER] [--out-dir DIR]
                                  [--threshold T] [--max-background-spread 18]

The view's picture is its file cut to its crop. Writes <out-dir>/<view>.png (white = vehicle, at the picture's
size; out-dir defaults to <project>/refs/masks), <view>-preview.jpg (the mask's edge drawn on the picture, to be
checked by eye) and <view>.json.
- A photo on a plain background: the background colour is the median of a strip round the picture's edge;
  pixels far from it are the vehicle (threshold from the picture unless --threshold); specks are removed, holes
  filled and the largest piece kept.
- A drawing (kind "drawing"): the mask is everything inside its outermost line.
- --seed <render>: for a photo on a busy background. A render of the model through the view's camera (an RGBA
  render from render_views.py, any size of the same shape) says roughly where the vehicle is; the edge is then
  found in a band round the render's outline (OpenCV GrabCut when present, otherwise a colour model).
Exit 1 when the silhouette touches the picture's edge, covers too little or too much of it, or (a photo without
a seed) the background is not plain enough; 2 on bad input.
"""
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, have_cv2, load_json, mask_boundary,  # noqa: E402
                     open_image, run, save_json, view_picture)

USAGE = ('python tools/mask_photo.py <view> [--project DIR] [--landmarks FILE] [--seed RENDER] [--out-dir DIR] '
         '[--threshold T]')


def otsu(values, bins=256):
    hist, edges = np.histogram(values, bins=bins)
    hist = hist.astype(float)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids)
    mu0 = m0 / np.maximum(w0, 1e-9)
    mu1 = (m0[-1] - m0) / np.maximum(w1, 1e-9)
    return float(mids[int(np.argmax(w0 * w1 * (mu0 - mu1) ** 2))])


def tidy(m, k):
    """Open, close (edge-padded so a vehicle crossing the edge stays there), fill holes, keep the largest piece."""
    st = np.ones((2 * k + 1, 2 * k + 1), bool)
    p = k + 1
    m = np.pad(m, p, mode='edge')
    m = ndimage.binary_closing(ndimage.binary_opening(m, structure=st), structure=st)[p:-p, p:-p]
    m = ndimage.binary_fill_holes(m)
    lab, n = ndimage.label(m)
    if n > 1:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        m = lab == (1 + int(np.argmax(sizes)))
    return m


def plain_photo(rgb, threshold):
    h, w = rgb.shape[:2]
    b = max(1, min(8, h // 4, w // 4))
    strip = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                            rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(strip, axis=0)
    sd = np.linalg.norm(strip - bg, axis=1)
    spread = float(np.percentile(sd[sd <= 3 * np.median(sd) + 3], 95))   # leave out a vehicle crossing the edge
    dist = np.linalg.norm(rgb - bg, axis=2)
    t = threshold if threshold is not None else max(otsu(dist), 2.5 * spread + 4.0)
    return tidy(dist > t, max(1, int(round(min(h, w) / 400)))), dict(background_rgb=bg.tolist(),
                                                                      background_spread=spread, threshold=float(t))


def drawing(rgb, threshold):
    grey = rgb.mean(2)
    t = threshold if threshold is not None else otsu(grey)
    ink = grey < t
    h, w = ink.shape
    k = max(1, int(round(min(h, w) / 300)))
    closed = ndimage.binary_dilation(ink, iterations=k)          # bridge small gaps in the outline
    filled = ndimage.binary_fill_holes(closed)
    lab, n = ndimage.label(filled)
    if n > 1:
        sizes = ndimage.sum(filled, lab, range(1, n + 1))
        filled = lab == (1 + int(np.argmax(sizes)))
    m = ndimage.binary_erosion(filled, iterations=k, border_value=1)
    return m, dict(ink_threshold=float(t))


def seeded(rgb, seed, band):
    h, w = seed.shape
    sure_fg = ndimage.binary_erosion(seed, iterations=band)
    maybe = ndimage.binary_dilation(seed, iterations=band)
    info = dict(band_px=band)
    if have_cv2():
        import cv2
        gc = np.full((h, w), cv2.GC_BGD, np.uint8)
        gc[maybe] = cv2.GC_PR_BGD
        gc[seed] = cv2.GC_PR_FGD
        gc[sure_fg] = cv2.GC_FGD
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(np.ascontiguousarray(rgb[:, :, ::-1].astype(np.uint8)), gc, None, bgd, fgd, 5,
                    cv2.GC_INIT_WITH_MASK)
        m = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
        info['segmentation'] = 'grabcut'
    else:
        ring = maybe & ~ndimage.binary_dilation(seed, iterations=max(1, band // 2))
        outer = ndimage.binary_dilation(maybe, iterations=band) & ~maybe
        bgs = rgb[ring | outer].reshape(-1, 3)
        fgs = rgb[sure_fg].reshape(-1, 3)
        if not len(bgs) or not len(fgs):
            raise BadInput('the seed leaves no room to learn the colours from')
        rng = np.random.default_rng(0)

        def centres(x, k=6):
            x = x[rng.choice(len(x), min(len(x), 4000), replace=False)]
            c = x[rng.choice(len(x), k, replace=False)]
            for _ in range(10):
                lab = np.argmin(((x[:, None] - c[None]) ** 2).sum(2), 1)
                c = np.array([x[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
            return c
        cb, cf = centres(bgs), centres(fgs)
        px = rgb[maybe & ~sure_fg]
        db = ((px[:, None] - cb[None]) ** 2).sum(2).min(1)
        df = ((px[:, None] - cf[None]) ** 2).sum(2).min(1)
        m = sure_fg.copy()
        m[maybe & ~sure_fg] = df < db
        info['segmentation'] = 'colour model'
    return tidy(m, max(1, int(round(min(h, w) / 400)))), info


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('view')
    ap.add_argument('--project', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--landmarks')
    ap.add_argument('--seed')
    ap.add_argument('--out-dir')
    ap.add_argument('--threshold', type=float)
    ap.add_argument('--max-background-spread', type=float, default=18.0)
    a = ap.parse(argv)
    project = os.path.abspath(a.project)
    lm = load_json(a.landmarks or os.path.join(project, 'data', 'landmarks.json'), 'landmarks.json')
    if not isinstance(lm, list):
        raise BadInput('landmarks.json must be a list of views')
    entry = next((e for e in lm if isinstance(e, dict) and e.get('view') == a.view), None)
    if entry is None or not entry.get('file'):
        raise BadInput('view %r is not in landmarks.json' % a.view)
    im, _ = view_picture(project, entry['file'], entry.get('crop'), 'picture of %r' % a.view)
    if im.width < 16 or im.height < 16:
        raise BadInput('picture is too small: %dx%d' % im.size)
    rgb = np.asarray(im.convert('RGB'), float)
    h, w = rgb.shape[:2]
    kind = entry.get('kind', 'photo')
    checks = {}
    if a.seed:
        from PIL import Image
        s = open_image(a.seed, 'seed render')
        if 'A' not in s.getbands():
            raise BadInput('the seed must be an RGBA render (its alpha is the vehicle)')
        if abs(s.width / s.height - w / h) > 0.01 * w / h:
            raise BadInput('the seed render is %dx%d, a different shape from the picture (%dx%d)'
                           % (s.width, s.height, w, h))
        sm = np.asarray(s.resize((w, h), Image.Resampling.BILINEAR).convert('RGBA'))[:, :, 3] > 127
        if not sm.any():
            raise BadInput('the seed render shows no vehicle')
        m, info = seeded(rgb, sm, max(2, int(round(0.03 * max(w, h)))))
        method = 'seed'
    elif kind == 'drawing':
        m, info = drawing(rgb, a.threshold)
        method = 'drawing'
    else:
        m, info = plain_photo(rgb, a.threshold)
        checks['background_plain'] = info['background_spread'] <= a.max_background_spread
        method = 'plain background'
    area = float(m.mean())
    checks['inside_picture'] = not bool(m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any())
    checks['sensible_area'] = 0.01 <= area <= 0.95
    out_dir = a.out_dir or os.path.join(project, 'refs', 'masks')
    os.makedirs(out_dir, exist_ok=True)
    from PIL import Image
    mask_path = os.path.join(out_dir, a.view + '.png')
    Image.fromarray((m * 255).astype(np.uint8), 'L').save(mask_path)
    prev = rgb.copy()
    prev[ndimage.binary_dilation(mask_boundary(m), iterations=max(1, int(round(min(h, w) / 500))))] = (255, 40, 40)
    prev_path = os.path.join(out_dir, a.view + '-preview.jpg')
    Image.fromarray(prev.astype(np.uint8)).save(prev_path, quality=90)
    ys, xs = np.nonzero(m)
    ok = all(checks.values())
    res = dict(view=a.view, kind=kind, method=method, file=entry['file'], crop=entry.get('crop'), mask=mask_path,
               preview=prev_path, width=w, height=h, area_fraction=area,
               bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None,
               checks=checks, passed=ok, seed=os.path.abspath(a.seed) if a.seed else None, **info)
    save_json(os.path.join(out_dir, a.view + '.json'), res)
    print('%s (%s): area %.1f%%  %s' % (a.view, method, 100 * area, 'pass' if ok else 'FAIL ' + ', '.join(
        k for k, v in checks.items() if not v)))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
