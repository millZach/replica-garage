"""Checks for the shared files described under "File formats" in CONTRACT.md.

Each check takes the parsed JSON and the file's name, and raises BadInput naming the file, the entry and the
missing or wrong key. Only the keys the tools read are checked; other keys are allowed.
"""
import math

from _common import BadInput

DIMENSIONS = ('length', 'width', 'height', 'wheelbase', 'track_front', 'track_rear', 'overhang_front',
              'tyre_diameter_front', 'tyre_diameter_rear', 'tyre_width_front', 'tyre_width_rear',
              'rim_diameter_front', 'rim_diameter_rear')
STUDIOS = ('soft', 'gloss', 'dark-paint')
SETTINGS_NUMBERS = ('metallic', 'roughness', 'coat', 'coat_roughness', 'transmission', 'ior', 'emission_strength')
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


def finishes(d, name='finishes.json'):
    _need(d, ('proof_look', 'looks'), name)
    if not isinstance(d['looks'], dict) or not d['looks']:
        raise BadInput('%s: "looks" must be a non-empty object' % name)
    if d['proof_look'] not in d['looks']:
        raise BadInput('%s: proof_look %r is not one of the looks' % (name, d['proof_look']))
    for lk, look in d['looks'].items():
        where = '%s look %r' % (name, lk)
        _need(look, ('studio', 'slots'), where)
        if look['studio'] not in STUDIOS:
            raise BadInput('%s: studio must be one of %s' % (where, ', '.join(STUDIOS)))
        if not isinstance(look['slots'], dict):
            raise BadInput('%s: "slots" must be an object of slot: settings' % where)
        for slot, st in look['slots'].items():
            sw = '%s slot %r' % (where, slot)
            if not isinstance(st, dict):
                raise BadInput('%s must be an object of settings' % sw)
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
