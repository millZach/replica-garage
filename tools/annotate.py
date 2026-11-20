"""Draw numbered marks on a picture for a fix note.

usage: python tools/annotate.py <in_picture> <out_picture> <marks.json>

marks.json is a list of marks, or {"marks": [...], "crop": [x0, y0, x1, y1]} (crop is optional, applied last).
Each mark is one of
  {"n": 1, "box": [x0, y0, x1, y1]}
  {"n": 2, "ellipse": [x0, y0, x1, y1]}
  {"n": 3, "outline": [[x, y], ...], "closed": true}
with an optional "color" ("#rrggbb") and "label" (text shown after the number). "n" defaults to the mark's place
in the list. Coordinates are pixels of the input picture; there is no scale field (one is refused).
Writes the marked picture and <out_picture>.json listing each mark's box in pixels.
Exit 1 when a mark lies partly or wholly outside the picture (it is still drawn, clipped), which usually means the
coordinates belong to a picture of another size. Exit 2 on bad input.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (ArgParser, BadInput, EXIT_GATE, EXIT_OK, font, load_json, number, open_image, run,  # noqa: E402
                     save_json)

USAGE = 'python tools/annotate.py <in_picture> <out_picture> <marks.json>'
KINDS = ('box', 'ellipse', 'outline')


def parse_marks(spec):
    crop = None
    if isinstance(spec, dict):
        if 'scale' in spec:
            raise BadInput('"scale" is not supported: give coordinates in pixels of the input picture')
        crop = spec.get('crop')
        marks = spec.get('marks')
    else:
        marks = spec
    if not isinstance(marks, list) or not marks:
        raise BadInput('marks.json needs a non-empty list of marks')
    out = []
    for i, m in enumerate(marks):
        if not isinstance(m, dict):
            raise BadInput('mark %d is not an object' % (i + 1))
        kinds = [k for k in KINDS if k in m]
        if len(kinds) != 1:
            raise BadInput('mark %d needs exactly one of %s' % (i + 1, ', '.join(KINDS)))
        k = kinds[0]
        if k == 'outline':
            pts = m[k]
            if not isinstance(pts, list) or len(pts) < 2 or any(not isinstance(p, (list, tuple)) or len(p) != 2
                                                                for p in pts):
                raise BadInput('mark %d outline needs two or more [x, y] points' % (i + 1))
            geom = [(number(p[0], 'x'), number(p[1], 'y')) for p in pts]
        else:
            b = m[k]
            if not isinstance(b, (list, tuple)) or len(b) != 4:
                raise BadInput('mark %d %s needs [x0, y0, x1, y1]' % (i + 1, k))
            x0, y0, x1, y1 = [number(c, k) for c in b]
            geom = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        col = m.get('color', '#ff2d2d')
        if not (isinstance(col, str) and col.startswith('#') and len(col) == 7):
            raise BadInput('mark %d color must be "#rrggbb"' % (i + 1))
        try:
            int(col[1:], 16)
        except ValueError:
            raise BadInput('mark %d color must be "#rrggbb"' % (i + 1))
        out.append(dict(n=m.get('n', i + 1), kind=k, geom=geom, closed=bool(m.get('closed', True)), color=col,
                        label=str(m.get('label', ''))))
    if crop is not None:
        if not isinstance(crop, (list, tuple)) or len(crop) != 4:
            raise BadInput('crop needs [x0, y0, x1, y1]')
        crop = [int(round(number(c, 'crop'))) for c in crop]
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            raise BadInput('crop box is empty')
    return out, crop


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('marks')
    a = ap.parse(argv)
    from PIL import ImageDraw
    im = open_image(a.src).convert('RGB')
    marks, crop = parse_marks(load_json(a.marks, 'marks file'))
    d = ImageDraw.Draw(im)
    lw = max(3, im.width // 450)
    f = font(max(16, im.width // 55))
    rows, ok = [], True
    for m in marks:
        col = m['color']
        if m['kind'] == 'box':
            d.rounded_rectangle(m['geom'], radius=lw * 4, outline=col, width=lw)
            bx = m['geom']
        elif m['kind'] == 'ellipse':
            d.ellipse(m['geom'], outline=col, width=lw)
            bx = m['geom']
        else:
            pts = m['geom']
            d.line(pts + ([pts[0]] if m['closed'] else []), fill=col, width=lw, joint='curve')
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            bx = (min(xs), min(ys), max(xs), max(ys))
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
        d.text((lx + pad, ly + pad // 2 - tb[1] + pad // 2), text, fill='white', font=f)
        rows.append(dict(n=m['n'], kind=m['kind'], box_px=[float(c) for c in bx], inside=bool(inside)))
    if crop:
        im = im.crop(tuple(crop))
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    try:
        im.save(a.dst)
    except (ValueError, OSError) as e:
        raise BadInput('cannot write %s (%s)' % (a.dst, e))
    save_json(a.dst + '.json', dict(source=os.path.abspath(a.src), output=os.path.abspath(a.dst), crop=crop,
                                    size=list(im.size), marks=rows, passed=bool(ok)))
    print(a.dst, im.size, 'all marks inside' if ok else 'MARKS OUTSIDE THE PICTURE: ' +
          ', '.join(str(r['n']) for r in rows if not r['inside']))
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
