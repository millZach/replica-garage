"""Judge one frozen round against the gate limits.

usage: python tools/gates.py <evidence/round-NN> [--limits FILE] [--skip gate,gate]

Reads the tools' results found anywhere in the round folder (cameras.json, dimensions.json, outline.json,
fairness.json, seating*.json, rays*.json, separation.json); cameras.json falls back to <project>/data/cameras.json.
Limits come from --limits, else <project>/data/gates.json when present, else the defaults below. The limits file is
{"limits": {key: value}, "skip": [gate, ...]} (a flat {key: value} object also works). Every limit that differs
from its default is printed. Each value is re-judged against the limits here; a tool's own pass flag is not used.

Gates and default limits:
  cameras      camera_rms_mm 12              each view's RMS error at its known points
  dimensions   dimension_error_mm 10         each overall dimension against the maker's figure
  outline      outline_median_px 3, outline_p95_px 8, at outline_ref_width_px 1600
  fairness     fairness_p99_deg 2.5, fairness_max_deg 5   away from named creases
  seating      seating_step_mm 3             step all round each part's edge
  double_skin  double_skin_count 0           painted surface behind a painted surface
  separation   separation_overlap_mm 0.5     overlap between separable parts; each part its own object, sane pivot
A gate with no evidence in the round counts as missing and fails the round unless it is skipped.
Writes <round>/gates.json: every gate with its measured value, limit and pass or fail, and one overall result.
Exit 0 when every gate passes, 1 when any fails or is missing, 2 on bad input.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ArgParser, BadInput, EXIT_GATE, EXIT_OK, load_json, number, run, save_json  # noqa: E402

USAGE = 'python tools/gates.py <evidence/round-NN> [--limits FILE] [--skip gate,gate]'

DEFAULTS = {
    'camera_rms_mm': 12.0,
    'dimension_error_mm': 10.0,
    'outline_median_px': 3.0,
    'outline_p95_px': 8.0,
    'outline_ref_width_px': 1600.0,
    'fairness_p99_deg': 2.5,
    'fairness_max_deg': 5.0,
    'seating_step_mm': 3.0,
    'double_skin_count': 0,
    'separation_overlap_mm': 0.5,
}
GATES = ('cameras', 'dimensions', 'outline', 'fairness', 'seating', 'double_skin', 'separation')


def load_limits(path):
    if not path:
        return dict(DEFAULTS), []
    d = load_json(path, 'limits file')
    if not isinstance(d, dict):
        raise BadInput('limits file must hold a JSON object')
    if 'gates' in d and 'limits' in d:          # an earlier gates.json result: reuse its limits
        lim, skip = d['limits'], d.get('skip', [])
    elif 'limits' in d or 'skip' in d:
        lim, skip = d.get('limits', {}), d.get('skip', [])
    else:
        lim, skip = d, []
    if not isinstance(lim, dict) or not isinstance(skip, list):
        raise BadInput('"limits" must be an object and "skip" a list')
    out = dict(DEFAULTS)
    for k, v in lim.items():
        if k not in DEFAULTS:
            raise BadInput('unknown limit %r (known: %s)' % (k, ', '.join(DEFAULTS)))
        out[k] = number(v, k)
    return out, list(skip)


def find(root, pred):
    hits = []
    for d, _, files in os.walk(root):
        for n in sorted(files):
            if n.endswith('.json') and n != 'gates.json' and pred(n):
                hits.append(os.path.join(d, n))
    return sorted(hits)


def bad(path, why):
    raise BadInput('%s: %s' % (path, why))


def collect(rnd, project, L):
    rows = []

    def add(gate, item, measured, limit, passed, source, **extra):
        r = dict(gate=gate, item=item, measured=measured, limit=limit, passed=bool(passed),
                 source=os.path.relpath(source, project) if source else None)
        r.update(extra)
        rows.append(r)

    cams = find(rnd, lambda n: n == 'cameras.json')
    if not cams and os.path.isfile(os.path.join(project, 'data', 'cameras.json')):
        cams = [os.path.join(project, 'data', 'cameras.json')]
    for p in cams:
        d = load_json(p)
        if not isinstance(d.get('cameras'), dict):
            bad(p, 'no "cameras" object')
        for v, c in d['cameras'].items():
            try:
                m = float(c['errors']['rms_mm'])
            except (KeyError, TypeError, ValueError):
                bad(p, 'camera %r has no errors.rms_mm' % v)
            add('cameras', v, m, L['camera_rms_mm'], m <= L['camera_rms_mm'], p, unit='mm')

    for p in find(rnd, lambda n: n == 'dimensions.json'):
        d = load_json(p)
        if not isinstance(d.get('dimensions'), dict):
            bad(p, 'no "dimensions" object')
        for k, e in d['dimensions'].items():
            if not isinstance(e, dict) or e.get('maker_mm') is None:
                continue
            err = e.get('error_mm')
            if err is None:
                add('dimensions', k, None, L['dimension_error_mm'], False, p, unit='mm', note='not measured')
            else:
                add('dimensions', k, float(err), L['dimension_error_mm'], abs(float(err)) <= L['dimension_error_mm'],
                    p, unit='mm')

    ref = L['outline_ref_width_px']
    for p in find(rnd, lambda n: n == 'outline.json'):
        d = load_json(p)
        if not isinstance(d.get('views'), dict):
            bad(p, 'no "views" object')
        for v, s in d['views'].items():
            if s.get('median_px') is None:
                add('outline', v + ' median', None, L['outline_median_px'], False, p, unit='px',
                    note=s.get('note', 'not measured'))
                continue
            k = ref / float(s['width'])
            med, p95 = float(s['median_px']) * k, float(s['p95_px']) * k
            add('outline', v + ' median', med, L['outline_median_px'], med <= L['outline_median_px'], p,
                unit='px at %g px width' % ref)
            add('outline', v + ' p95', p95, L['outline_p95_px'], p95 <= L['outline_p95_px'], p,
                unit='px at %g px width' % ref)

    for p in find(rnd, lambda n: n == 'fairness.json'):
        d = load_json(p)
        if not isinstance(d.get('panels'), dict):
            bad(p, 'no "panels" object')
        for k, s in d['panels'].items():
            p99, mx = s.get('p99_deg'), s.get('max_deg')
            if p99 is None:
                add('fairness', k, None, L['fairness_p99_deg'], False, p, unit='deg', note='no faces measured')
                continue
            add('fairness', k + ' p99', float(p99), L['fairness_p99_deg'], float(p99) <= L['fairness_p99_deg'], p,
                unit='deg')
            add('fairness', k + ' max', float(mx), L['fairness_max_deg'], float(mx) <= L['fairness_max_deg'], p,
                unit='deg')

    for p in find(rnd, lambda n: n.startswith('seating')):
        d = load_json(p)
        if 'max_abs_step_mm' not in d:
            bad(p, 'no max_abs_step_mm')
        m = d['max_abs_step_mm']
        item = '%s on %s' % (d.get('part'), d.get('panel'))
        add('seating', item, m, L['seating_step_mm'], m is not None and float(m) <= L['seating_step_mm'], p,
            unit='mm')

    for p in find(rnd, lambda n: n.startswith('rays')):
        d = load_json(p)
        if d.get('double_skins') is None:
            continue                            # rays traced without painted materials named: nothing to judge
        n = int(d['double_skins'])
        add('double_skin', os.path.relpath(p, rnd), n, L['double_skin_count'], n <= L['double_skin_count'], p,
            unit='pixels')

    for p in find(rnd, lambda n: n == 'separation.json'):
        d = load_json(p)
        if not isinstance(d.get('parts'), list) or not isinstance(d.get('overlaps'), list):
            bad(p, 'needs "parts" and "overlaps" lists')
        for part in d['parts']:
            add('separation', '%s own object' % part.get('name'), bool(part.get('own_object')), True,
                part.get('own_object'), p)
            add('separation', '%s pivot' % part.get('name'), bool(part.get('pivot_ok')), True, part.get('pivot_ok'), p)
        worst = max([float(o['depth_mm']) for o in d['overlaps']] or [0.0])
        add('separation', 'level %s worst overlap' % d.get('level'), worst, L['separation_overlap_mm'],
            worst <= L['separation_overlap_mm'], p, unit='mm')
    return rows


def main(argv):
    ap = ArgParser(usage_line=USAGE)
    ap.add_argument('round')
    ap.add_argument('--limits')
    ap.add_argument('--skip', default='')
    a = ap.parse(argv)
    rnd = os.path.abspath(a.round)
    if not os.path.isdir(rnd):
        raise BadInput('round folder not found: %s' % a.round)
    project = os.path.dirname(os.path.dirname(rnd))
    lim_path = a.limits
    if not lim_path and os.path.isfile(os.path.join(project, 'data', 'gates.json')):
        lim_path = os.path.join(project, 'data', 'gates.json')
    L, skip = load_limits(lim_path)
    skip = sorted(set(skip) | {s.strip() for s in a.skip.split(',') if s.strip()})
    for s in skip:
        if s not in GATES:
            raise BadInput('unknown gate %r to skip (gates: %s)' % (s, ', '.join(GATES)))
    changed = {k: dict(default=DEFAULTS[k], used=L[k]) for k in DEFAULTS if L[k] != DEFAULTS[k]}
    for k, c in changed.items():
        print('changed limit: %s %g -> %g' % (k, c['default'], c['used']))
    for s in skip:
        print('skipped gate:', s)
    rows = [r for r in collect(rnd, project, L) if r['gate'] not in skip]
    for r in rows:
        if isinstance(r['measured'], float) and not math.isfinite(r['measured']):
            r['measured'] = None
    missing = [g for g in GATES if g not in skip and not any(r['gate'] == g for r in rows)]
    ok = all(r['passed'] for r in rows) and not missing
    by_gate = {g: ('skipped' if g in skip else 'missing' if g in missing else
                   'pass' if all(r['passed'] for r in rows if r['gate'] == g) else 'fail') for g in GATES}
    out = dict(round=os.path.basename(rnd), limits=L, changed_limits=changed, limits_file=lim_path, skip=skip,
               summary=by_gate, missing=missing, gates=rows, passed=bool(ok))
    save_json(os.path.join(rnd, 'gates.json'), out)
    for g in GATES:
        print('%-12s %s' % (g, by_gate[g]))
    for r in rows:
        if not r['passed']:
            print('  FAIL %-11s %-32s measured %s limit %s' % (r['gate'], r['item'], r['measured'], r['limit']))
    print('overall:', 'PASS' if ok else 'FAIL')
    return EXIT_OK if ok else EXIT_GATE


if __name__ == '__main__':
    run(main)
