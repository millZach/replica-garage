"""Judge one frozen round against the gate limits.

usage: python tools/gates.py <evidence/round-NN> [--limits FILE] [--min-precise 3] [--skip gate,gate]

Reads the tools' results anywhere in the round folder: cameras.json (else <project>/data/cameras.json),
dimensions.json, outline.json, fairness.json, seating*.json, rays*.json, separation.json. Limits: the defaults in
tools/default_limits.json, overlaid by --limits or <project>/data/limits.json; every limit that differs from its
default is printed and recorded. Each value is judged here against those limits; a tool's own pass flag is not
used.

Gates (limit names as in default_limits.json):
  cameras      at least --min-precise (default 3) views whose RMS is within camera_rms_mm (and not flat)
  dimensions   each maker's dimension within dimension_error_mm (estimated ones are left out)
  outline      each precise view: median within outline_median_px and 95th percentile within outline_p95_px,
               at outline_ref_width_px image width
  fairness     each panel: 99th percentile within fairness_p99_deg, maximum within fairness_max_deg
  seating      each seated part: step within seating_step_mm all round its edge
  double_skin  painted surfaces within the stack depth behind another: at most double_skin_count
  separation   each part its own object with its pivot; overlap within separation_overlap_mm. Needed only when
               the project has data/parts.json.
A needed gate with no evidence in the round is missing and fails the round unless skipped with --skip.
Writes <round>/gates.json: every gate with its value, its limit and pass or fail, the overall result and the
changed limits. Exit 0 when every gate passes, 1 when any fails or is missing, 2 on bad input.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _formats as F  # noqa: E402
from _common import (ArgParser, BadInput, DEFAULT_LIMITS, EXIT_GATE, EXIT_OK, TOOLS_DIR, load_json,  # noqa: E402
                     project_limits, read_limits, run, save_json)

USAGE = 'python tools/gates.py <evidence/round-NN> [--limits FILE] [--skip gate,gate]'
GATES = ('cameras', 'dimensions', 'outline', 'fairness', 'seating', 'double_skin', 'separation')


def find(root, pred):
    hits = []
    for d, _, files in os.walk(root):
        for n in sorted(files):
            if n.endswith('.json') and n != 'gates.json' and pred(n):
                hits.append(os.path.join(d, n))
    return sorted(hits)


def bad(path, why):
    raise BadInput('%s: %s' % (path, why))


def num(v):
    return None if v is None else float(v)


def collect(rnd, project, L, min_precise):
    rows = []

    def add(gate, item, measured, limit, passed, source, counted=True, **extra):
        r = dict(gate=gate, item=item, measured=measured, limit=limit, passed=bool(passed), counted=counted,
                 source=os.path.relpath(source, project).replace(os.sep, '/') if source else None)
        r.update(extra)
        rows.append(r)

    grades = {}
    cams = find(rnd, lambda n: n == 'cameras.json')
    if not cams and os.path.isfile(os.path.join(project, 'data', 'cameras.json')):
        cams = [os.path.join(project, 'data', 'cameras.json')]
    for p in cams[:1]:
        cams = F.cameras(load_json(p), os.path.relpath(p, project))
        n = 0
        for v, c in cams.items():
            precise = float(c['rms_mm']) <= L['camera_rms_mm'] and not c.get('planar', False)
            grades[v] = 'precise' if precise else 'visual'
            n += precise
            add('cameras', v, float(c['rms_mm']), L['camera_rms_mm'], precise, p, counted=False, unit='mm',
                grade=grades[v])
        add('cameras', 'precise views', n, min_precise, n >= min_precise, p, unit='views')

    for p in find(rnd, lambda n: n == 'dimensions.json'):
        d = load_json(p)
        if not isinstance(d.get('dimensions'), dict):
            bad(p, 'no "dimensions" object')
        for k, e in d['dimensions'].items():
            if not isinstance(e, dict) or e.get('maker_mm') is None or not e.get('judged', True):
                continue
            err = num(e.get('error_mm'))
            add('dimensions', k, err, L['dimension_error_mm'],
                err is not None and abs(err) <= L['dimension_error_mm'], p, unit='mm',
                **({} if err is not None else {'note': e.get('note', 'not measured')}))

    ref = L['outline_ref_width_px']
    for p in find(rnd, lambda n: n == 'outline.json'):
        d = load_json(p)
        if not isinstance(d.get('views'), dict):
            bad(p, 'no "views" object')
        for v, s in d['views'].items():
            counted = grades.get(v, s.get('grade')) == 'precise'
            if s.get('median_px') is None:
                add('outline', v, None, L['outline_median_px'], False, p, counted=counted, unit='px',
                    note=s.get('note', 'not measured'))
                continue
            k = ref / float(s['width'])
            med, p95 = float(s['median_px']) * k, float(s['p95_px']) * k
            unit = 'px at %g px width' % ref
            add('outline', v + ' median', med, L['outline_median_px'], med <= L['outline_median_px'], p,
                counted=counted, unit=unit)
            add('outline', v + ' p95', p95, L['outline_p95_px'], p95 <= L['outline_p95_px'], p, counted=counted,
                unit=unit)

    for p in find(rnd, lambda n: n == 'fairness.json'):
        d = load_json(p)
        if not isinstance(d.get('panels'), dict):
            bad(p, 'no "panels" object')
        for k, s in d['panels'].items():
            p99, mx = num(s.get('p99_deg')), num(s.get('max_deg'))
            if p99 is None:
                add('fairness', k, None, L['fairness_p99_deg'], False, p, unit='deg', note='no faces measured')
                continue
            add('fairness', k + ' p99', p99, L['fairness_p99_deg'], p99 <= L['fairness_p99_deg'], p, unit='deg')
            add('fairness', k + ' max', mx, L['fairness_max_deg'], mx <= L['fairness_max_deg'], p, unit='deg')

    for p in find(rnd, lambda n: n.startswith('seating')):
        d = load_json(p)
        seats = d.get('seats')
        if not isinstance(seats, list):
            bad(p, 'no "seats" list')
        for s in seats:
            m = num(s.get('max_abs_step_mm'))
            add('seating', '%s on %s' % (s.get('part'), s.get('on')), m, L['seating_step_mm'],
                m is not None and m <= L['seating_step_mm'], p, unit='mm',
                **({} if m is not None else {'note': s.get('note', 'not measured')}))

    for p in find(rnd, lambda n: n.startswith('rays')):
        d = load_json(p)
        if d.get('double_skins') is None:
            continue                            # rays traced at chosen pixels only: nothing to judge
        n = int(d['double_skins'])
        add('double_skin', os.path.relpath(p, rnd).replace(os.sep, '/'), n, L['double_skin_count'],
            n <= L['double_skin_count'], p, unit='places')

    for p in find(rnd, lambda n: n == 'separation.json'):
        d = load_json(p)
        if not isinstance(d.get('parts'), list) or not isinstance(d.get('overlaps'), list):
            bad(p, 'needs "parts" and "overlaps" lists')
        for part in d['parts']:
            add('separation', '%s own object' % part.get('part'), bool(part.get('own_object')), True,
                part.get('own_object'), p)
            add('separation', '%s pivot' % part.get('part'), bool(part.get('pivot_ok')), True, part.get('pivot_ok'),
                p)
        worst = max([float(o['depth_mm']) for o in d['overlaps']] or [0.0])
        add('separation', 'level %s worst overlap' % d.get('level'), worst, L['separation_overlap_mm'],
            worst <= L['separation_overlap_mm'], p, unit='mm')
    return rows


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('round')
    ap.add_argument('--limits')
    ap.add_argument('--skip', default='')
    ap.add_argument('--min-precise', type=int, default=3)
    a = ap.parse(argv)
    rnd = os.path.abspath(a.round)
    if not os.path.isdir(rnd):
        raise BadInput('round folder not found: %s' % a.round)
    project = os.path.dirname(os.path.dirname(rnd))
    L, used = project_limits(project, a.limits)
    shipped = dict(DEFAULT_LIMITS)
    dl = os.path.join(TOOLS_DIR, 'default_limits.json')
    if os.path.isfile(dl):
        shipped.update(read_limits(dl))
    skip = sorted({s.strip() for s in a.skip.split(',') if s.strip()})
    for s in skip:
        if s not in GATES:
            raise BadInput('unknown gate %r to skip (gates: %s)' % (s, ', '.join(GATES)))
    changed = {k: dict(default=shipped[k], used=L[k]) for k in shipped if L[k] != shipped[k]}
    for k, c in changed.items():
        print('changed limit: %s %g -> %g' % (k, c['default'], c['used']))
    for s in skip:
        print('skipped gate:', s)
    rows = [r for r in collect(rnd, project, L, a.min_precise) if r['gate'] not in skip]
    for r in rows:
        if isinstance(r['measured'], float) and not math.isfinite(r['measured']):
            r['measured'] = None
    needed = [g for g in GATES if g not in skip and
              (g != 'separation' or os.path.isfile(os.path.join(project, 'data', 'parts.json')))]
    missing = [g for g in needed if not any(r['gate'] == g and r['counted'] for r in rows)]
    counted = [r for r in rows if r['counted']]
    ok = all(r['passed'] for r in counted) and not missing
    summary = {}
    for g in GATES:
        if g in skip:
            summary[g] = 'skipped'
        elif g in missing:
            summary[g] = 'missing'
        elif g not in needed and not any(r['gate'] == g for r in rows):
            summary[g] = 'not needed'
        else:
            summary[g] = 'pass' if all(r['passed'] for r in counted if r['gate'] == g) else 'fail'
    out = dict(round=os.path.basename(rnd), limits=L, limits_file=used, changed_limits=changed, skip=skip,
               summary=summary, missing=missing, gates=rows, passed=bool(ok))
    save_json(os.path.join(rnd, 'gates.json'), out)
    for g in GATES:
        print('%-12s %s' % (g, summary[g]))
    for r in counted:
        if not r['passed']:
            print('  FAIL %-11s %-32s measured %s limit %s' % (r['gate'], r['item'], r['measured'], r['limit']))
    print('overall:', 'PASS' if ok else 'FAIL')
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
