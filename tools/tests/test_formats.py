"""The file-format checks of _formats.py, and the cases from the contract that are easiest to test directly."""
import pytest

import _formats as F
from _common import BadInput
from conftest import DIMS, VEHICLE, camera_at, camera_entry, read_json, run_tool, write_json

PART = {'part': 'door_l', 'fixed_to': 'shell', 'pivot': [500, -925, 700], 'level': 3, 'basis': 'measured'}


def test_parts_fixed_to_is_another_part_or_shell():
    F.parts([PART, dict(PART, part='door_l_glass', fixed_to='door_l')])
    with pytest.raises(BadInput, match="fixed_to 'roof' must be another part in the list or \"shell\""):
        F.parts([dict(PART, fixed_to='roof')])
    with pytest.raises(BadInput, match='fixed to itself'):
        F.parts([dict(PART, fixed_to='door_l')])
    with pytest.raises(BadInput, match="missing key 'basis'"):
        F.parts([{k: v for k, v in PART.items() if k != 'basis'}])


def test_every_format_names_its_missing_key():
    cases = [
        (F.vehicle, {k: v for k, v in VEHICLE.items() if k != 'generation'}, 'generation'),
        (F.landmarks, [{'view': 'a', 'file': 'a.png', 'kind': 'photo', 'points': {}}], 'steer_deg'),
        (F.landmarks, [{'view': 'a', 'file': 'a.png', 'kind': 'photo', 'steer_deg': 0, 'points': {},
                        'focal_mm': 50}], 'sensor_mm'),
        (F.pixels, [{'name': 'x', 'view': 'a', 'u': 1}], 'v'),
        (F.build, [{'assembly': 'body', 'version': 0, 'seats': [{'part': 'lamp'}]}], 'on'),
        (F.finishes, {'proof_look': 'w', 'looks': {'w': {'slots': {}}}}, 'studio'),
        (F.marks, [{'n': 1, 'picture': 'a.png', 'shape': 'box'}], 'points'),
    ]
    for fn, data, key in cases:
        with pytest.raises(BadInput, match="missing key '%s'" % key):
            fn(data)
    c = camera_entry(camera_at((0.0, -5000.0, 800.0)))
    del c['rms_px']
    with pytest.raises(BadInput, match="missing key 'rms_px'"):
        F.cameras({'cameras': {'side': c}})
    with pytest.raises(BadInput, match="missing key 'depends_on'"):
        F.manifest({'assembly': 'body', 'version': 0, 'sha256': '0' * 64}, 'body', 0)


def test_estimated_must_name_dimensions():
    F.vehicle(dict(VEHICLE, estimated=['overhang_front']))
    with pytest.raises(BadInput, match='estimated'):
        F.vehicle(dict(VEHICLE, estimated=['wingspan']))


def test_missing_dimension_takes_its_points_away(project):
    """Without the tyre widths there are no hub points: a view that marks one is refused, naming it."""
    dims = {k: v for k, v in DIMS.items() if not k.startswith('tyre_width')}
    write_json(project / 'data' / 'vehicle.json', dict(VEHICLE, dimensions=dims))
    from conftest import blank_picture
    blank_picture(project / 'refs' / 'photos' / 'a.png', 100, 100)
    write_json(project / 'data' / 'landmarks.json', [{'view': 'a', 'file': 'refs/photos/a.png', 'kind': 'photo',
                                                      'steer_deg': 0, 'points': {
        'hub_fl': [1, 1], 'contact_fl': [2, 2], 'contact_fr': [3, 3], 'contact_rl': [4, 4], 'contact_rr': [5, 5],
        'front_extreme': [6, 6]}}])
    r = run_tool('solve_cameras.py', '--project', project)
    assert r.returncode == 2 and 'hub_fl' in r.stderr and 'dimensions may be missing' in r.stderr


def test_gates_count_a_part_not_built_as_information(project):
    rnd = project / 'evidence' / 'round-01'
    write_json(project / 'data' / 'parts.json', [PART])
    write_json(rnd / 'separation.json', {'level': 3, 'overlaps': [], 'parts': [
        {'part': 'door_l', 'status': 'not built', 'own_object': None, 'pivot_ok': None}]})
    r = run_tool('gates.py', rnd, '--skip', 'cameras,dimensions,outline,fairness,seating,daylight,double_skin')
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_json(rnd / 'gates.json')['summary']['separation'] == 'pass'


def test_finishes_extended_settings_and_surface():
    valid = {
        'proof_look': 'cabin',
        'end_fill_watts': 40,
        'showroom': {'card_watts': 300, 'floor_roughness': 0.12},
        'color_management': {'view_transform': 'AgX', 'look': 'None', 'exposure': 0.1},
        'looks': {
            'cabin': {
                'studio': 'interior',
                'color_management': {'view_transform': 'AgX', 'exposure': -0.2},
                'slots': {
                    'seat': {'base_color': [0.05, 0.05, 0.06], 'roughness': 0.55, 'sheen': 0.2,
                             'sheen_roughness': 0.5, 'surface': 'leather', 'bump_strength': 0.12,
                             'bump_scale_mm': 2.0},
                    'insert': {'base_color': [0.04, 0.04, 0.04], 'surface': 'perforated'},
                    'trim': {'base_color': [0.5, 0.5, 0.5], 'metallic': 1.0, 'anisotropic': 0.6,
                             'specular_ior_level': 0.5, 'surface': 'brushed'},
                    'weave': {'surface': 'carbon'},
                    'carpet': {'surface': 'fabric'},
                    'tyre': {'surface': 'rubber'},
                },
            }
        },
    }
    F.finishes(valid)
    bad = dict(valid, looks={'cabin': {'studio': 'interior', 'slots': {'seat': {'surface': 'velvet'}}}})
    with pytest.raises(BadInput, match='surface must be one of'):
        F.finishes(bad)
    bad_cm = dict(valid, color_management={'exposure': 'high'})
    with pytest.raises(BadInput, match='color_management.exposure'):
        F.finishes(bad_cm)


def test_details_format():
    valid = [
        {'name': 'cabin_34', 'camera_mm': [1200, -1400, 1200], 'target_mm': [1400, 0, 750],
         'lens_mm': 35, 'resolution': [800, 600], 'lighting': 'interior', 'hide': ['roof', 'glass*'],
         'denoise': False, 'toggle_part': 'steering_wheel', 'targets_mm': {'cluster': [900, -350, 780]}},
        {'name': 'quarter_strip', 'camera_mm': [2200, -2500, 950], 'target_mm': [2100, -850, 700],
         'lighting': 'strip-sweep', 'strip_angles_deg': [-20, 0, 20]},
    ]
    F.details(valid)
    with pytest.raises(BadInput, match='has no views'):
        F.details([])
    with pytest.raises(BadInput, match="missing key 'target_mm'"):
        F.details([{'name': 'a', 'camera_mm': [0, 0, 0]}])
    with pytest.raises(BadInput, match='listed twice'):
        F.details([valid[0], dict(valid[0])])
    with pytest.raises(BadInput, match='lighting must be'):
        F.details([dict(valid[0], lighting='neon')])
