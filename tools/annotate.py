"""Draw the numbered marks for one picture from marks.json.

usage: python tools/annotate.py <picture> <marks.json> [--out FILE]

marks.json is a list of {"n": number, "picture": path, "shape": "box" | "ellipse" | "outline",
"points": [[u, v], ...]} (optional: "closed" for an outline, default true; "color" "#rrggbb"; "label" text).
A box or ellipse takes two corner points; an outline two or more points. "picture" is read relative to the folder
marks.json is in (or as given); the marks drawn are those whose picture is this picture (same file, or the same
file name when no path matches). Coordinates are pixels of that picture.
Writes the marked picture (default <picture's folder>/<name>-marked.<ext>) and <out>.json listing each mark.
Exit 1 when a mark lies partly or wholly outside the picture (it is still drawn, clipped), which usually means
its pixels belong to another picture; 2 on bad input, including no marks for this picture.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, font, load_json, number, open_image, run,  # noqa: E402
                     save_json)

USAGE = 'python tools/annotate.py <picture> <marks.json> [--out FILE]'
SHAPES = ('box', 'ellipse', 'outline')


def same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def marks_for(picture, marks_path):
    marks = load_json(marks_path, 'marks file')
    if not isinstance(marks, list):
        raise BadInput('marks.json must be a list of marks')
    base = os.path.dirname(os.path.abspath(marks_path))
    exact, by_name = [], []
    for i, m in enumerate(marks):
        if not isinstance(m, dict):
            raise BadInput('mark %d is not an object' % (i + 1))
        for k in ('n', 'picture', 'shape', 'points'):
            if k not in m:
                raise BadInput('mark %d has no %r' % (i + 1, k))
        p = str(m['picture'])
        cands = [p] if os.path.isabs(p) else [os.path.join(base, p), p]
        if any(same(c, picture) for c in cands):
            exact.append(m)
        elif os.path.basename(p) == os.path.basename(picture):
            by_name.append(m)
    chosen = exact or by_name
    if not chosen:
        raise BadInput('marks.json has no marks for %s' % picture)
    out = []
    for m in chosen:
        shape, pts = m['shape'], m['points']
        if shape not in SHAPES:
            raise BadInput('mark %s: shape must be one of %s' % (m['n'], ', '.join(SHAPES)))
        if not isinstance(pts, list) or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in pts):
            raise BadInput('mark %s: points must be a list of [u, v]' % m['n'])
        pts = [(number(p[0], 'u'), number(p[1], 'v')) for p in pts]
        if shape in ('box', 'ellipse') and len(pts) != 2:
            raise BadInput('mark %s: a %s takes two corner points' % (m['n'], shape))
        if shape == 'outline' and len(pts) < 2:
            raise BadInput('mark %s: an outline takes two or more points' % m['n'])
        col = m.get('color', '#ff2d2d')
        try:
            ok = isinstance(col, str) and col.startswith('#') and len(col) == 7 and int(col[1:], 16) >= 0
        except ValueError:
            ok = False
        if not ok:
            raise BadInput('mark %s: color must be "#rrggbb"' % m['n'])
        out.append(dict(n=m['n'], shape=shape, points=pts, closed=bool(m.get('closed', True)), color=col,
                        label=str(m.get('label', ''))))
    return out


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('picture')
    ap.add_argument('marks')
    ap.add_argument('--out')
    a = ap.parse(argv)
    from PIL import ImageDraw
    im = open_image(a.picture).convert('RGB')
    marks = marks_for(a.picture, a.marks)
    stem, ext = os.path.splitext(a.picture)
    dst = a.out or stem + '-marked' + (ext or '.png')
    d = ImageDraw.Draw(im)
    lw = max(3, im.width // 450)
    f = font(max(16, im.width // 55))
    rows, ok = [], True
    for m in marks:
        pts, col = m['points'], m['color']
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        bx = (min(xs), min(ys), max(xs), max(ys))
        if m['shape'] == 'box':
            d.rounded_rectangle(bx, radius=lw * 4, outline=col, width=lw)
        elif m['shape'] == 'ellipse':
            d.ellipse(bx, outline=col, width=lw)
        else:
            d.line(pts + ([pts[0]] if m['closed'] else []), fill=col, width=lw, joint='curve')
        inside = bx[0] >= 0 and bx[1] >= 0 and bx[2] <= im.width - 1 and bx[3] <= im.height - 1
        ok &= inside
        text = str(m['n']) + ((' ' + m['label']) if m['label'] else '')
        tb = d.textbbox((0, 0), text, font=f)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        pad = lw * 2
        lx = min(max(0, bx[0]), max(0, im.width - tw - 2 * pad))
        ly = bx[1] - th - pad * 3
        if ly < 0:
            ly = min(bx[3] + pad, im.height - th - pad * 3)
        ly = max(0, ly)
        d.rectangle([lx, ly, lx + tw + pad * 2, ly + th + pad * 3], fill=col)
        d.text((lx + pad, ly + pad - tb[1]), text, fill='white', font=f)
        rows.append(dict(n=m['n'], shape=m['shape'], box_px=[float(c) for c in bx], inside=bool(inside)))
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    try:
        im.save(dst)
    except (ValueError, OSError) as e:
        raise BadInput('cannot write %s (%s)' % (dst, e))
    save_json(dst + '.json', dict(picture=os.path.abspath(a.picture), output=os.path.abspath(dst), size=list(im.size),
                                  marks=rows, passed=bool(ok)))
    print(dst, im.size, 'all marks inside' if ok else 'MARKS OUTSIDE THE PICTURE: ' +
          ', '.join(str(r['n']) for r in rows if not r['inside']))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
