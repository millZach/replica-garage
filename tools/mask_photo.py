"""Cut the vehicle's silhouette out of one photo taken on a plain background.

usage: python tools/mask_photo.py <photo> [--out-dir refs/masks] [--view NAME] [--threshold T]
                                  [--max-background-spread 18] [--border 8]

Writes <out-dir>/<view>.png (white vehicle, black background), <out-dir>/<view>-preview.jpg (the mask's edge
drawn on the photo, for a person or agent to check) and <out-dir>/<view>.json. The view name defaults to the
photo's file name without its extension. --out-dir defaults to refs/masks beside the photo's refs/photos folder.

The background colour is the median of a strip round the picture's border. Pixels far from it in colour are the
vehicle; the threshold is chosen from the picture (Otsu) unless --threshold is given. Small specks are removed,
holes are filled and the largest connected piece is kept.
Exit 1 when the background is not plain enough (its colour spread is over --max-background-spread), when the
silhouette touches the picture's edge (the vehicle is cut off) or when nothing sensible was found. Exit 2 on bad
input.
"""
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, mask_boundary, open_image, run,  # noqa: E402
                     save_json)

USAGE = ('python tools/mask_photo.py <photo> [--out-dir refs/masks] [--view NAME] [--threshold T] '
         '[--max-background-spread 18] [--border 8]')


def otsu(values, bins=256):
    hist, edges = np.histogram(values, bins=bins)
    hist = hist.astype(float)
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids)
    mu0 = m0 / np.maximum(w0, 1e-9)
    mu1 = (m0[-1] - m0) / np.maximum(w1, 1e-9)
    between = w0 * w1 * (mu0 - mu1) ** 2
    return float(mids[int(np.argmax(between))])


def make_mask(rgb, border, threshold):
    h, w = rgb.shape[:2]
    b = max(1, min(border, h // 4, w // 4))
    strip = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                            rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(strip, axis=0)
    sd = np.linalg.norm(strip - bg, axis=1)
    # spread of the background itself: leave out border pixels that belong to a vehicle crossing the edge
    spread = float(np.percentile(sd[sd <= 3 * np.median(sd) + 3], 95))
    dist = np.linalg.norm(rgb - bg, axis=2)
    t = threshold if threshold is not None else max(otsu(dist), 2.5 * spread + 4.0)
    m = dist > t
    k = max(1, int(round(min(h, w) / 400)))
    st = np.ones((2 * k + 1, 2 * k + 1), bool)
    p = k + 1                                  # pad by repeating the edge so a vehicle crossing it stays there
    m = np.pad(m, p, mode='edge')
    m = ndimage.binary_opening(m, structure=st)
    m = ndimage.binary_closing(m, structure=st)
    m = m[p:-p, p:-p]
    m = ndimage.binary_fill_holes(m)
    lab, n = ndimage.label(m)
    if n > 1:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        m = lab == (1 + int(np.argmax(sizes)))
    return m, bg, spread, t


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('photo')
    ap.add_argument('--out-dir')
    ap.add_argument('--view')
    ap.add_argument('--threshold', type=float)
    ap.add_argument('--max-background-spread', type=float, default=18.0)
    ap.add_argument('--border', type=int, default=8)
    a = ap.parse(argv)
    im = open_image(a.photo, 'photo')
    if im.width < 16 or im.height < 16:
        raise BadInput('photo is too small: %dx%d' % im.size)
    rgb = np.asarray(im.convert('RGB'), float)
    view = a.view or os.path.splitext(os.path.basename(a.photo))[0]
    out_dir = a.out_dir
    if not out_dir:
        ref = os.path.dirname(os.path.dirname(os.path.abspath(a.photo)))
        out_dir = os.path.join(ref, 'masks')
    os.makedirs(out_dir, exist_ok=True)

    m, bg, spread, t = make_mask(rgb, a.border, a.threshold)
    h, w = m.shape
    area = float(m.mean())
    edge_touch = bool(m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any())
    checks = {
        'background_plain': spread <= a.max_background_spread,
        'inside_picture': not edge_touch,
        'sensible_area': 0.01 <= area <= 0.95,
    }
    from PIL import Image
    mask_path = os.path.join(out_dir, view + '.png')
    Image.fromarray((m * 255).astype(np.uint8), 'L').save(mask_path)
    prev = rgb.copy()
    edge = ndimage.binary_dilation(mask_boundary(m), iterations=max(1, int(round(min(h, w) / 500))))
    prev[edge] = (255, 40, 40)
    prev_path = os.path.join(out_dir, view + '-preview.jpg')
    Image.fromarray(prev.astype(np.uint8)).save(prev_path, quality=90)
    ys, xs = np.nonzero(m)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
    ok = all(checks.values())
    res = dict(view=view, photo=os.path.abspath(a.photo), mask=mask_path, preview=prev_path, width=w, height=h,
               background_rgb=[float(c) for c in bg], background_spread=spread,
               max_background_spread=a.max_background_spread, threshold=float(t), area_fraction=area, bbox_px=bbox,
               checks=checks, passed=ok)
    save_json(os.path.join(out_dir, view + '.json'), res)
    print('%s: area %.1f%%  background spread %.1f  %s' % (view, 100 * area, spread,
                                                          'pass' if ok else 'FAIL ' + ', '.join(
                                                              k for k, v in checks.items() if not v)))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
