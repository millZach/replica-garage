"""Checks for the shared files described under "File formats" in CONTRACT.md.

Each check takes the parsed JSON and the file's name, and raises BadInput naming the file, the entry and the
missing or wrong key. Only the keys the tools read are checked; other keys are allowed.
"""
import math

from _common import BadInput

DIMENSIONS = ('length', 'width', 'height', 'wheelbase', 'track_front', 'track_rear', 'overhang_front',
              'tyre_diameter_front', 'tyre_diameter_rear', 'tyre_width_front', 'tyre_width_rear',
              'rim_diameter_front', 'rim_diameter_rear')
STUDIOS = ('soft', 'gloss', 'dark-paint', 'interior')
SURFACES = ('leather', 'perforated', 'brushed', 'carbon', 'fabric', 'rubber')
SETTINGS_NUMBERS = ('metallic', 'roughness', 'coat', 'coat_roughness', 'transmission', 'ior', 'emission_strength',
                    'specular_ior_level', 'anisotropic', 'sheen', 'sheen_roughness', 'bump_strength',
                    'bump_scale_mm')
SETTINGS_COLOURS = ('base_color', 'emission')


def _need(obj, keys, where):
    if not isinstance(obj, dict):
        raise BadInput('%s must be a JSON object' % where)
    for k in keys:
        if k not in obj:
            raise BadInput('%s: missing key %r' % (where, k))


def _num(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise BadInput('%s must be a number' % where)
    return float(v)


def _vec(v, n, where):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise BadInput('%s must be a list of %d numbers' % (where, n))
    return [_num(x, where) for x in v]


def _list(d, where):
    if not isinstance(d, list):
        raise BadInput('%s must be a JSON list' % where)
    return d


def vehicle(d, name='vehicle.json'):
    _need(d, ('maker', 'model', 'generation', 'years', 'trim', 'dimensions'), name)
    dims = d['dimensions']
    if not isinstance(dims, dict):
        raise BadInput('%s: "dimensions" must be an object' % name)
    for k in DIMENSIONS:
        if k in dims and dims[k] is not None:
            _num(dims[k], '%s: dimensions.%s' % (name, k))
    est = d.get('estimated', [])
    if not isinstance(est, list) or any(e not in DIMENSIONS for e in est):
        raise BadInput('%s: "estimated" must be a list of dimension names (%s)' % (name, ', '.join(DIMENSIONS)))
    pts = d.get('points', {})
    if not isinstance(pts, dict):
        raise BadInput('%s: "points" must be an object of name: [x, y, z]' % name)
    for k, v in pts.items():
        _vec(v, 3, '%s: points.%s' % (name, k))
    return d


def landmarks(d, name='landmarks.json'):
    seen = set()
    for i, e in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(e, ('view', 'file', 'kind', 'steer_deg', 'points'), where)
        where = '%s view %r' % (name, e['view'])
        if e['view'] in seen:
            raise BadInput('%s is listed twice' % where)
        seen.add(e['view'])
        if e['kind'] not in ('photo', 'drawing'):
            raise BadInput('%s: "kind" must be "photo" or "drawing"' % where)
        _num(e['steer_deg'], where + ': steer_deg')
        if e.get('crop') is not None:
            _vec(e['crop'], 4, where + ': crop')
        if ('focal_mm' in e) != ('sensor_mm' in e):
            raise BadInput('%s: missing key %r' % (where, 'sensor_mm' if 'focal_mm' in e else 'focal_mm'))
        if not isinstance(e['points'], dict):
            raise BadInput('%s: "points" must be an object of name: [u, v]' % where)
        for k, v in e['points'].items():
            _vec(v, 2, '%s: points.%s' % (where, k))
    if not d:
        raise BadInput('%s has no views' % name)
    return d


def pixels(d, name='pixels file'):
    for i, e in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(e, ('name', 'view', 'u', 'v'), where)
        _num(e['u'], where + ': u')
        _num(e['v'], where + ': v')
    if not d:
        raise BadInput('%s is empty' % name)
    return d


CAMERA_KEYS = ('kind', 'position_mm', 'rotation', 'centre_px', 'width', 'height', 'steer_deg', 'rms_mm', 'rms_px',
               'grade')


def camera(c, view, name='cameras.json'):
    where = '%s camera %r' % (name, view)
    _need(c, CAMERA_KEYS, where)
    if c['kind'] not in ('perspective', 'orthographic'):
        raise BadInput('%s: "kind" must be "perspective" or "orthographic"' % where)
    _need(c, ('focal_px',) if c['kind'] == 'perspective' else ('scale_px_per_mm',), where)
    if c['grade'] not in ('precise', 'visual'):
        raise BadInput('%s: "grade" must be "precise" or "visual"' % where)
    _vec(c['position_mm'], 3, where + ': position_mm')
    if not isinstance(c['rotation'], list) or len(c['rotation']) != 3:
        raise BadInput('%s: rotation must be a 3 x 3 list' % where)
    for r in c['rotation']:
        _vec(r, 3, where + ': rotation')
    _vec(c['centre_px'], 2, where + ': centre_px')
    for k in ('width', 'height', 'steer_deg', 'rms_mm', 'rms_px'):
        _num(c[k], '%s: %s' % (where, k))
    return c


def cameras(d, name='cameras.json'):
    _need(d, ('cameras',), name)
    if not isinstance(d['cameras'], dict) or not d['cameras']:
        raise BadInput('%s: "cameras" must be a non-empty object of view: camera' % name)
    for v, c in d['cameras'].items():
        camera(c, v, name)
    return d['cameras']


def _check_cm(cm, where):
    if not isinstance(cm, dict):
        raise BadInput('%s: color_management must be a JSON object' % where)
    if 'view_transform' in cm and not isinstance(cm['view_transform'], str):
        raise BadInput('%s: color_management.view_transform must be a string' % where)
    if 'look' in cm and cm['look'] is not None and not isinstance(cm['look'], str):
        raise BadInput('%s: color_management.look must be a string' % where)
    if 'exposure' in cm and cm['exposure'] is not None:
        _num(cm['exposure'], '%s: color_management.exposure' % where)


def finishes(d, name='finishes.json'):
    _need(d, ('proof_look', 'looks'), name)
    if 'style' in d and d['style'] not in ('showroom', 'studio', 'daylight'):
        raise BadInput('%s: style must be showroom, studio or daylight' % name)
    if 'sky' in d and not isinstance(d['sky'], str):
        raise BadInput('%s: sky must be the path of an image under refs/' % name)
    if 'end_fill_watts' in d and d['end_fill_watts'] is not None:
        _num(d['end_fill_watts'], '%s: end_fill_watts' % name)
    if 'showroom' in d and d['showroom'] is not None and not isinstance(d['showroom'], dict):
        raise BadInput('%s: showroom must be a JSON object' % name)
    if 'color_management' in d and d['color_management'] is not None:
        _check_cm(d['color_management'], name)
    if not isinstance(d['looks'], dict) or not d['looks']:
        raise BadInput('%s: "looks" must be a non-empty object' % name)
    if d['proof_look'] not in d['looks']:
        raise BadInput('%s: proof_look %r is not one of the looks' % (name, d['proof_look']))
    for lk, look in d['looks'].items():
        where = '%s look %r' % (name, lk)
        _need(look, ('studio', 'slots'), where)
        if look['studio'] not in STUDIOS:
            raise BadInput('%s: studio must be one of %s' % (where, ', '.join(STUDIOS)))
        if 'color_management' in look and look['color_management'] is not None:
            _check_cm(look['color_management'], where)
        if not isinstance(look['slots'], dict):
            raise BadInput('%s: "slots" must be an object of slot: settings' % where)
        for slot, st in look['slots'].items():
            sw = '%s slot %r' % (where, slot)
            if not isinstance(st, dict):
                raise BadInput('%s must be an object of settings' % sw)
            if 'surface' in st and st['surface'] is not None and st['surface'] not in SURFACES:
                raise BadInput('%s: surface must be one of %s' % (sw, ', '.join(SURFACES)))
            for k in SETTINGS_NUMBERS:
                if k in st:
                    _num(st[k], '%s: %s' % (sw, k))
            for k in SETTINGS_COLOURS:
                if k in st:
                    _vec(st[k], 3, '%s: %s' % (sw, k))
    return d


def build(d, name='build.json'):
    seen = set()
    for i, e in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(e, ('assembly', 'version', 'seats'), where)
        where = '%s assembly %r' % (name, e['assembly'])
        if e['assembly'] in seen:
            raise BadInput('%s is listed twice' % where)
        seen.add(e['assembly'])
        _num(e['version'], where + ': version')
        for j, s in enumerate(_list(e['seats'], where + ': seats')):
            _need(s, ('part', 'on'), '%s seat %d' % (where, j + 1))
        if 'seams' in e and e['seams'] is not None:
            seams(e['seams'], '%s: seams' % where)
    return d


def manifest(d, assembly, version, name='manifest.json'):
    _need(d, ('assembly', 'version', 'sha256', 'depends_on'), name)
    if d['assembly'] != assembly:
        raise BadInput('%s: assembly is %r, the folder says %r' % (name, d['assembly'], assembly))
    if int(_num(d['version'], name + ': version')) != int(version):
        raise BadInput('%s: version is %r, the folder says %02d' % (name, d['version'], int(version)))
    if not isinstance(d['sha256'], str) or len(d['sha256']) != 64:
        raise BadInput('%s: sha256 must be the 64 hex digits of the module file' % name)
    if not isinstance(d['depends_on'], list):
        raise BadInput('%s: depends_on must be a list of assemblies' % name)
    return d


def parts(d, name='parts.json'):
    seen = set()
    for i, e in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(e, ('part', 'fixed_to', 'pivot', 'level', 'basis'), where)
        where = '%s part %r' % (name, e['part'])
        if e['part'] in seen:
            raise BadInput('%s is listed twice' % where)
        seen.add(e['part'])
        _vec(e['pivot'], 3, where + ': pivot')
        if e['level'] not in (2, 3):
            raise BadInput('%s: level must be 2 or 3' % where)
        if e['basis'] not in ('measured', 'reconstructed'):
            raise BadInput('%s: basis must be "measured" or "reconstructed"' % where)
        if 'assembly' in e and not isinstance(e['assembly'], str):
            raise BadInput('%s: assembly must be the name of an assembly' % where)
    names = {e['part'] for e in d}
    for e in d:
        if e['fixed_to'] != 'shell' and e['fixed_to'] not in names:
            raise BadInput('%s part %r: fixed_to %r must be another part in the list or "shell"'
                           % (name, e['part'], e['fixed_to']))
        if e['fixed_to'] == e['part']:
            raise BadInput('%s part %r is fixed to itself' % (name, e['part']))
    return d


def marks(d, name='marks.json'):
    for i, m in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(m, ('n', 'picture', 'shape', 'points'), where)
        if m['shape'] not in ('box', 'ellipse', 'outline'):
            raise BadInput('%s: shape must be box, ellipse or outline' % where)
        for p in _list(m['points'], where + ': points'):
            _vec(p, 2, where + ': points')
    return d


def details(d, name='details.json'):
    seen = set()
    for i, e in enumerate(_list(d, name)):
        where = '%s entry %d' % (name, i + 1)
        _need(e, ('name', 'camera_mm', 'target_mm'), where)
        where = '%s view %r' % (name, e['name'])
        if e['name'] in seen:
            raise BadInput('%s is listed twice' % where)
        seen.add(e['name'])
        _vec(e['camera_mm'], 3, where + ': camera_mm')
        _vec(e['target_mm'], 3, where + ': target_mm')
        if 'up' in e and e['up'] is not None:
            _vec(e['up'], 3, where + ': up')
        if 'lens_mm' in e and e['lens_mm'] is not None:
            _num(e['lens_mm'], where + ': lens_mm')
        if 'resolution' in e and e['resolution'] is not None:
            _vec(e['resolution'], 2, where + ': resolution')
        if 'lighting' in e and e['lighting'] is not None and e['lighting'] not in ('style', 'studio', 'interior',
                                                                                  'strip-sweep'):
            raise BadInput('%s: lighting must be style, studio, interior or strip-sweep' % where)
        if 'hide' in e and e['hide'] is not None and not isinstance(e['hide'], list):
            raise BadInput('%s: hide must be a list of part patterns' % where)
        if 'strip_angles_deg' in e and e['strip_angles_deg'] is not None:
            for a in _list(e['strip_angles_deg'], where + ': strip_angles_deg'):
                _num(a, where + ': strip_angles_deg')
        if 'targets_mm' in e and e['targets_mm'] is not None:
            if not isinstance(e['targets_mm'], dict):
                raise BadInput('%s: targets_mm must be an object of label: [x, y, z]' % where)
            for k, v in e['targets_mm'].items():
                _vec(v, 3, '%s: targets_mm.%s' % (where, k))
    if not d:
        raise BadInput('%s has no views' % name)
    return d


SEAM_KINDS = ('body', 'glass')
MACRO_TRIAGE_VIEWS = ('front', 'rear', 'left', 'front-left', 'rear-right')
MACRO_TRIAGE_CHECKS = (
    'lamp_shapes_angles',
    'zero_daylight_leaks',
    'smooth_roofline_greenhouse',
    'flush_panel_alignment',
)
MACRO_SCORE_CAP = 55


def seams(d, name='seams.json'):
    if isinstance(d, list):
        cfg = {'pairs': d}
    elif isinstance(d, dict):
        _need(d, ('pairs',), name)
        cfg = dict(d)
    else:
        raise BadInput('%s must be a list of {"a", "b"} pairs or {"pairs": [...]}' % name)
    for k in ('min_gap_mm', 'max_gap_mm', 'max_flush_mm', 'search_radius_mm'):
        if k in cfg and cfg[k] is not None:
            _num(cfg[k], '%s: %s' % (name, k))
    if 'min_gap_mm' in cfg and 'max_gap_mm' in cfg and cfg['min_gap_mm'] is not None and cfg['max_gap_mm'] is not None:
        if float(cfg['max_gap_mm']) <= float(cfg['min_gap_mm']):
            raise BadInput('%s: max_gap_mm must exceed min_gap_mm' % name)
    pairs = _list(cfg['pairs'], name + ': pairs')
    for i, p in enumerate(pairs):
        where = '%s pair %d' % (name, i + 1)
        _need(p, ('a', 'b'), where)
        if not isinstance(p['a'], str) or not p['a'].strip() or not isinstance(p['b'], str) or not p['b'].strip():
            raise BadInput('%s: "a" and "b" must be non-empty part names' % where)
        if p['a'].strip() == p['b'].strip():
            raise BadInput('%s: a seam pair cannot compare %r to itself' % (where, p['a']))
        if 'kind' in p and p['kind'] is not None and p['kind'] not in SEAM_KINDS:
            raise BadInput('%s: kind must be one of %s' % (where, ', '.join(SEAM_KINDS)))
        for k in ('min_gap_mm', 'max_gap_mm', 'max_flush_mm', 'search_radius_mm'):
            if k in p and p[k] is not None:
                _num(p[k], '%s: %s' % (where, k))
    return cfg


def zones(d, name='zones.json'):
    items = d.get('zones') if isinstance(d, dict) else d
    items = _list(items, name)
    if not items:
        raise BadInput('%s has no zones' % name)
    seen = set()
    for i, z in enumerate(items):
        where = '%s entry %d' % (name, i + 1)
        _need(z, ('id',), where)
        zid = str(z['id']).strip()
        if not zid:
            raise BadInput('%s: id must be non-empty' % where)
        where = '%s zone %r' % (name, zid)
        if zid in seen:
            raise BadInput('%s is listed twice' % where)
        seen.add(zid)
        if ('ref' in z) != ('render' in z):
            raise BadInput('%s: "ref" and "render" must be given together' % where)
        for bk in ('box_px', 'box_norm', 'box_img_norm'):
            if bk in z and z[bk] is not None:
                b = _vec(z[bk], 4, '%s: %s' % (where, bk))
                if b[2] <= b[0] or b[3] <= b[1]:
                    raise BadInput('%s: %s must have x1 > x0 and y1 > y0' % (where, bk))
    return items


def macro_triage(d, name='macro-triage.json'):
    _need(d, ('views', 'checks', 'passed'), name)
    views = _list(d['views'], name + ': views')
    vset = {str(v) for v in views}
    missing_views = [v for v in MACRO_TRIAGE_VIEWS if v not in vset]
    if missing_views:
        raise BadInput('%s: Stage 1 views missing required view(s): %s' % (name, ', '.join(missing_views)))
    checks = d['checks']
    if not isinstance(checks, dict):
        raise BadInput('%s: "checks" must be a JSON object' % name)
    results = {}
    for k in MACRO_TRIAGE_CHECKS:
        if k not in checks:
            raise BadInput('%s: missing check %r' % (name, k))
        v = checks[k]
        if isinstance(v, bool):
            results[k] = v
        elif isinstance(v, dict) and isinstance(v.get('passed'), bool):
            results[k] = v['passed']
        else:
            raise BadInput('%s: check %r must be a boolean or {"passed": bool}' % (name, k))
    if not isinstance(d['passed'], bool):
        raise BadInput('%s: "passed" must be a boolean' % name)
    expected = all(results.values())
    if d['passed'] != expected:
        raise BadInput('%s: "passed" is %s but the 4 binary checks evaluate to %s' % (name, d['passed'], expected))
    if not expected and d.get('score_cap') is not None:
        cap = _num(d['score_cap'], name + ': score_cap')
        if cap > MACRO_SCORE_CAP:
            raise BadInput('%s: score_cap on a Stage 1 fail must be <= %d, got %g' % (name, MACRO_SCORE_CAP, cap))
    return d
