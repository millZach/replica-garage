"""Unit tests for Zach's 4 replica-garage improvements:
1. CPU daylight-leak ray test (daylight.py) and body/glass seam gap & flush step checks (seams.py / seating.py)
2. 1:1 Hero Zone Comparison Sheet (compare_zones.py)
3. Strict 2-stage "Macro First" Blind Judge gate (macro-triage.json, _formats.py, accept.py, gates.py)
4. Contract & documentation guardrails (Single Shared Boundary Function rule)
"""
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

import _formats as F
import compare_zones as CZ
import daylight as DL
import seams as SM
from _common import BadInput
from conftest import (blank_picture, camera_at, camera_entry, landmark_entry, read_json, run_blender, run_tool,
                      write_json)
from test_gates_wait import fill_round


# ------------------------------------------------------------------ 1A. Pure-CPU daylight logic

def test_daylight_classify_catches_holes_wedges_inner_and_ignores_glass():
    # 12x12 grid: solid body silhouette in [2..9, 2..9], background outside
    hk = np.zeros((12, 12), dtype=np.int8)
    sil = np.zeros((12, 12), dtype=bool)
    oids = np.full((12, 12), -1, dtype=np.int32)
    hk[2:10, 2:10] = 1
    sil[2:10, 2:10] = True
    oids[2:10, 2:6] = 10   # left panel
    oids[2:10, 6:10] = 20  # right panel

    # Clean closed body with a glass window in [3:5, 3:5]: 0 leaks
    hk[3:5, 3:5] = 2
    res_ok = DL.classify_grid(hk, sil, oids, wedge_px=2)
    assert int(res_ok['all_leaks'].sum()) == 0

    # Add an interior background slit (non-glass hole inside body silhouette)
    hk_hole = hk.copy()
    sil_hole = sil.copy()
    hk_hole[6, 4:7] = 0
    sil_hole[6, 4:7] = False
    res_hole = DL.classify_grid(hk_hole, sil_hole, oids, wedge_px=2)
    assert int(res_hole['background_holes'].sum()) == 3
    assert int(res_hole['all_leaks'].sum()) == 3

    # Add an edge wedge gap between panel 10 (col 5) and panel 20 (col 7) at the top border of silhouette (row 2)
    hk_wedge = hk.copy()
    sil_wedge = sil.copy()
    oids_wedge = oids.copy()
    hk_wedge[2:4, 6] = 0
    sil_wedge[2:4, 6] = False
    oids_wedge[2:4, 6] = -1
    res_wedge = DL.classify_grid(hk_wedge, sil_wedge, oids_wedge, wedge_px=2)
    assert int(res_wedge['wedge_gaps'].sum()) == 2

    # Add an exposed rg_inner face (code 3) and panel backface (code 4)
    hk_in = hk.copy()
    hk_in[7, 7] = 3
    hk_in[8, 8] = 4
    res_in = DL.classify_grid(hk_in, sil, oids, wedge_px=2)
    assert int(res_in['inner_leaks'].sum()) == 1
    assert int(res_in['backface_leaks'].sum()) == 1
    assert int(res_in['all_leaks'].sum()) == 2


# ------------------------------------------------------------------ 1B. Pure-CPU seam geometry logic

def _rect_panel_segs(x0, x1, y0, y1, z):
    """Four outer-skin boundary segments of a flat horizontal panel with +Z outward normal."""
    n = np.array([0.0, 0.0, 1.0])
    return [
        dict(p0=[x0, y0, z], p1=[x1, y0, z], tangent=[1.0, 0.0, 0.0], inward=[0.0, 1.0, 0.0], normal=n),
        dict(p0=[x1, y0, z], p1=[x1, y1, z], tangent=[0.0, 1.0, 0.0], inward=[-1.0, 0.0, 0.0], normal=n),
        dict(p0=[x1, y1, z], p1=[x0, y1, z], tangent=[-1.0, 0.0, 0.0], inward=[0.0, -1.0, 0.0], normal=n),
        dict(p0=[x0, y1, z], p1=[x0, y0, z], tangent=[0.0, -1.0, 0.0], inward=[1.0, 0.0, 0.0], normal=n),
    ]


def test_seam_geometry_gap_and_flush_thresholds():
    hood = _rect_panel_segs(-0.9, 0.0, -0.5, 0.5, 0.8)
    # 3.0 mm shut line, 1.0 mm flush step -> PASS (1.5-5.0 mm gap, <= 2.0 mm flush)
    bumper_ok = _rect_panel_segs(-1.2, -0.903, -0.5, 0.5, 0.801)
    r_ok = SM.measure_seam_geometry(hood, bumper_ok)
    assert r_ok['passed'] is True
    assert r_ok['min_gap_mm'] == pytest.approx(3.0, abs=0.05)
    assert r_ok['max_gap_mm'] == pytest.approx(3.0, abs=0.05)
    assert r_ok['max_abs_flush_mm'] == pytest.approx(1.0, abs=0.05)

    # 0.8 mm gap -> FAIL (< 1.5 mm)
    bumper_tight = _rect_panel_segs(-1.2, -0.9008, -0.5, 0.5, 0.8)
    r_tight = SM.measure_seam_geometry(hood, bumper_tight)
    assert r_tight['passed'] is False and r_tight['gap_passed'] is False and r_tight['flush_passed'] is True
    assert r_tight['min_gap_mm'] == pytest.approx(0.8, abs=0.05)

    # 7.5 mm gap -> FAIL (> 5.0 mm)
    bumper_wide = _rect_panel_segs(-1.2, -0.9075, -0.5, 0.5, 0.8)
    r_wide = SM.measure_seam_geometry(hood, bumper_wide)
    assert r_wide['passed'] is False and r_wide['gap_passed'] is False
    assert r_wide['max_gap_mm'] == pytest.approx(7.5, abs=0.05)

    # 3.2 mm flush step -> FAIL (> 2.0 mm)
    bumper_step = _rect_panel_segs(-1.2, -0.903, -0.5, 0.5, 0.8032)
    r_step = SM.measure_seam_geometry(hood, bumper_step)
    assert r_step['passed'] is False and r_step['gap_passed'] is True and r_step['flush_passed'] is False
    assert r_step['max_abs_flush_mm'] == pytest.approx(3.2, abs=0.05)

    # Overlapping panels (-2.0 mm) -> FAIL (< 1.5 mm)
    bumper_overlap = _rect_panel_segs(-1.2, -0.898, -0.5, 0.5, 0.8)
    r_ov = SM.measure_seam_geometry(hood, bumper_overlap)
    assert r_ov['passed'] is False and r_ov['min_gap_mm'] < 0.0


# ------------------------------------------------------------------ 2. compare_zones.py (1:1 Hero Zone Sheet)

def _draw_car_image(path, w, h, rgb=(180, 40, 40), rgba=False):
    mode = 'RGBA' if rgba else 'RGB'
    bg = (0, 0, 0, 0) if rgba else (220, 220, 220)
    im = Image.new(mode, (w, h), bg)
    d = ImageDraw.Draw(im)
    fill = rgb + (255,) if rgba else rgb
    d.rectangle([w // 8, h // 4, 7 * w // 8, 3 * h // 4], fill=fill)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.save(path)


def test_compare_zones_defaults_and_custom_config(project, tmp_path):
    assert run_tool('compare_zones.py').returncode == 2
    renders = tmp_path / 'renders'
    landmarks = []
    for v, rgb in (('front', (200, 40, 40)), ('rear', (40, 120, 200)), ('side', (40, 180, 90)),
                   ('rear-right', (180, 140, 40))):
        rp = project / 'refs' / 'photos' / (v + '.png')
        _draw_car_image(rp, 400, 240, rgb=rgb, rgba=False)
        _draw_car_image(renders / (v + '.png'), 200, 120, rgb=rgb, rgba=True)
        landmarks.append(landmark_entry(v, 'refs/photos/' + v + '.png'))
    write_json(project / 'data' / 'landmarks.json', landmarks)

    out1 = tmp_path / 'zones_default'
    r = run_tool('compare_zones.py', '--project', project, '--renders', renders, '--out', out1,
                 '--panel-width', 240, '--save-crops')
    assert r.returncode == 0, r.stdout + r.stderr
    meta = read_json(out1 / 'compare_zones.json')
    assert os.path.isfile(out1 / 'hero-zones.jpg')
    assert len(meta['zones']) == 5
    assert [z['id'] for z in meta['zones']] == [z['id'] for z in CZ.DEFAULT_ZONES]
    assert all(z['same_camera_scale'] for z in meta['zones'])
    assert all(os.path.isfile(z['crops']['ref']) and os.path.isfile(z['crops']['render']) for z in meta['zones'])
    sheet = Image.open(out1 / 'hero-zones.jpg')
    assert sheet.width == 2 * 240 + 3 * 10

    # Custom per-vehicle data/zones.json with exact box_px
    zones_cfg = write_json(project / 'data' / 'zones.json', [
        {'id': 'nose', 'label': '(a) Front headlamps & nose', 'view': 'front', 'box_px': [50, 60, 350, 180]},
        {'id': 'tail', 'label': '(b) Rear hatch glass & tail lamps', 'view': 'rear', 'box_px': [60, 50, 340, 170]},
    ])
    out2 = tmp_path / 'zones_custom'
    r2 = run_tool('compare_zones.py', '--project', project, '--renders', renders, '--out', out2,
                  '--zones', zones_cfg, '--panel-width', 200, '--sheet-name', 'custom.jpg')
    assert r2.returncode == 0, r2.stdout + r2.stderr
    m2 = read_json(out2 / 'compare_zones.json')
    assert os.path.isfile(out2 / 'custom.jpg')
    assert m2['zones'][0]['ref_crop_px'] == [50, 60, 350, 180]
    assert m2['zones'][0]['render_crop_px'] == [50, 60, 350, 180]


# ------------------------------------------------------------------ 3. Strict 2-Stage "Macro First" Judge + accept.py + gates.py

def _triage_payload(passed=True, failed_key=None):
    checks = {k: {'passed': True, 'note': 'ok'} for k in F.MACRO_TRIAGE_CHECKS}
    if not passed:
        checks[failed_key or 'zero_daylight_leaks'] = {'passed': False, 'note': 'slit at tail lamp'}
    return {
        'views': list(F.MACRO_TRIAGE_VIEWS),
        'checks': checks,
        'passed': passed,
        'score_cap': None if passed else 55,
    }


def test_macro_triage_format_and_accept_blocking(project):
    F.macro_triage(_triage_payload(True))
    F.macro_triage(_triage_payload(False, 'lamp_shapes_angles'))
    # Inconsistent passed=True with a failing check must raise BadInput
    bad = _triage_payload(False, 'flush_panel_alignment')
    bad['passed'] = True
    with pytest.raises(BadInput, match='evaluate to False'):
        F.macro_triage(bad)
    # Missing required view must raise BadInput
    bad_views = _triage_payload(True)
    bad_views['views'] = ['front', 'rear', 'left']
    with pytest.raises(BadInput, match='missing required view'):
        F.macro_triage(bad_views)
    # Score cap > 55 on fail must raise BadInput
    bad_cap = _triage_payload(False)
    bad_cap['score_cap'] = 80
    with pytest.raises(BadInput, match='score_cap'):
        F.macro_triage(bad_cap)

    # accept.py enforcement with --round
    src = project / 'src'
    os.makedirs(src, exist_ok=True)
    (src / 'body.py').write_text('def build(ctx):\n    pass\n', encoding='utf-8')
    (src / 'cabin.py').write_text('def build(ctx):\n    pass\n', encoding='utf-8')
    rnd = project / 'evidence' / 'round-01'
    write_json(rnd / 'macro-triage.json', _triage_payload(False, 'zero_daylight_leaks'))

    # Detail assembly (cabin) MUST be blocked (exit 1) while Stage 1 fails
    r_blk = run_tool('accept.py', 'cabin', '0', '--project', project, '--round', rnd)
    assert r_blk.returncode == 1, r_blk.stdout + r_blk.stderr
    assert 'BLOCKED BY STAGE 1 MACRO TRIAGE' in r_blk.stdout
    assert 'zero_daylight_leaks' in r_blk.stdout
    assert not (project / 'accepted' / 'cabin' / '00' / 'cabin.py').exists()

    # Macro fix assembly (body) IS allowed so builders can fix the macro fault
    r_mac = run_tool('accept.py', 'body', '1', '--project', project, '--round', rnd)
    assert r_mac.returncode == 0, r_mac.stdout + r_mac.stderr
    assert 'accepting macro fix pass' in r_mac.stdout
    assert (project / 'accepted' / 'body' / '01' / 'body.py').is_file()

    # With --require-stage1, even body is blocked until Stage 1 passes
    assert run_tool('accept.py', 'body', '2', '--project', project, '--round', rnd, '--require-stage1').returncode == 1

    # Once all 4 Stage 1 checks pass, cabin is accepted cleanly
    write_json(rnd / 'macro-triage.json', _triage_payload(True))
    r_ok = run_tool('accept.py', 'cabin', '0', '--project', project, '--round', rnd)
    assert r_ok.returncode == 0, r_ok.stdout + r_ok.stderr
    assert (project / 'accepted' / 'cabin' / '00' / 'cabin.py').is_file()


def test_gates_enforces_daylight_seams_and_macro_triage(project):
    rnd = project / 'evidence' / 'round-01'
    fill_round(rnd)
    # Missing daylight.json fails gates.py
    os.remove(rnd / 'daylight.json')
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['daylight'] == 'missing'

    # Failing daylight.json (total_leaks=2) fails gates.py
    write_json(rnd / 'daylight.json', {'total_leaks': 2, 'background_leaks': 2, 'passed': False})
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['daylight'] == 'fail'

    # Passing daylight.json passes again
    write_json(rnd / 'daylight.json', {'total_leaks': 0, 'background_leaks': 0, 'passed': True})
    assert run_tool('gates.py', rnd).returncode == 0

    # Declaring data/seams.json requires seams evidence
    write_json(project / 'data' / 'seams.json', {'pairs': [{'a': 'hood', 'b': 'front_bumper'}]})
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['seams'] == 'missing'

    # Failing seam (gap 6.5 mm > 5.0 mm) fails gates.py
    write_json(rnd / 'seams.json', {'pairs': [
        {'a': 'hood', 'b': 'front_bumper', 'min_gap_mm': 2.0, 'max_gap_mm': 6.5, 'max_abs_flush_mm': 0.8}
    ]})
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['seams'] == 'fail'

    # Passing seam (gap 2.2..3.1 mm, flush 0.8 mm) passes gates.py
    write_json(rnd / 'seams.json', {'pairs': [
        {'a': 'hood', 'b': 'front_bumper', 'min_gap_mm': 2.2, 'max_gap_mm': 3.1, 'max_abs_flush_mm': 0.8}
    ]})
    assert run_tool('gates.py', rnd).returncode == 0
    assert read_json(rnd / 'gates.json')['summary']['seams'] == 'pass'

    # Failing macro-triage.json fails gates.py when present
    write_json(rnd / 'macro-triage.json', _triage_payload(False, 'smooth_roofline_greenhouse'))
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['macro_triage'] == 'fail'

    write_json(rnd / 'macro-triage.json', _triage_payload(True))
    assert run_tool('gates.py', rnd).returncode == 0
    assert read_json(rnd / 'gates.json')['summary']['macro_triage'] == 'pass'


def test_seams_and_zones_formats():
    F.seams([{'a': 'hood', 'b': 'bumper'}, {'a': 'hatch_glass', 'b': 'hatch', 'kind': 'glass'}])
    with pytest.raises(BadInput, match='compare'):
        F.seams([{'a': 'hood', 'b': 'hood'}])
    with pytest.raises(BadInput, match='max_gap_mm must exceed'):
        F.seams({'min_gap_mm': 5.0, 'max_gap_mm': 2.0, 'pairs': [{'a': 'hood', 'b': 'bumper'}]})
    F.zones([{'id': 'nose', 'view': 'front', 'box_norm': [0.0, 0.2, 1.0, 0.8]}])
    with pytest.raises(BadInput, match='x1 > x0'):
        F.zones([{'id': 'nose', 'box_px': [200, 100, 100, 300]}])


# ------------------------------------------------------------------ 4. Blender CPU integration tests

@pytest.mark.blender
def test_daylight_blender_passes_closed_and_catches_slit_and_inner(blender, scenes, project, tmp_path):
    assert run_blender(blender, scenes['plain'], 'daylight.py').returncode == 2

    out_ok = tmp_path / 'dl_ok'
    r_ok = run_blender(blender, scenes['daylight_ok'], 'daylight.py', '--project', project,
                       '--out', out_ok, '--grid', 64, '--views', 'front,rear,left,right,front-left,rear-right')
    assert r_ok.returncode == 0, r_ok.stdout[-2000:] + r_ok.stderr[-2000:]
    j_ok = read_json(out_ok / 'daylight.json')
    assert j_ok['passed'] is True and j_ok['total_leaks'] == 0
    assert j_ok['views']['rear']['glass_rays'] > 0

    out_slit = tmp_path / 'dl_slit'
    r_slit = run_blender(blender, scenes['daylight_slit'], 'daylight.py', '--project', project,
                         '--out', out_slit, '--grid', 64, '--views', 'rear')
    assert r_slit.returncode == 1, r_slit.stdout[-2000:] + r_slit.stderr[-2000:]
    j_slit = read_json(out_slit / 'daylight.json')
    assert j_slit['passed'] is False and j_slit['background_leaks'] > 0

    out_inner = tmp_path / 'dl_inner'
    r_inner = run_blender(blender, scenes['daylight_inner'], 'daylight.py', '--project', project,
                          '--out', out_inner, '--grid', 64, '--views', 'front')
    assert r_inner.returncode == 1, r_inner.stdout[-2000:] + r_inner.stderr[-2000:]
    j_inner = read_json(out_inner / 'daylight.json')
    assert j_inner['passed'] is False and j_inner['inner_leaks'] > 0


@pytest.mark.blender
def test_seams_and_extended_seating_in_blender(blender, scenes, project, tmp_path):
    assert run_blender(blender, scenes['seams_test'], 'seams.py').returncode == 2

    # Clean body-to-body and glass-to-body pairs pass seams.py
    good_cfg = write_json(project / 'data' / 'seams.json', {
        'pairs': [
            {'a': 'hood', 'b': 'front_bumper', 'kind': 'body'},
            {'a': 'hatch_glass', 'b': 'hatch', 'kind': 'glass'},
        ]
    })
    out_good = tmp_path / 'seams_good'
    r_good = run_blender(blender, scenes['seams_test'], 'seams.py', '--project', project,
                         '--seams', good_cfg, '--out', out_good)
    assert r_good.returncode == 0, r_good.stdout[-2000:] + r_good.stderr[-2000:]
    jg = read_json(out_good / 'seams.json')
    assert jg['passed'] is True
    assert jg['pairs'][0]['min_gap_mm'] == pytest.approx(3.0, abs=0.1)
    assert jg['pairs'][0]['max_abs_flush_mm'] == pytest.approx(1.0, abs=0.1)
    assert jg['pairs'][1]['min_gap_mm'] == pytest.approx(2.5, abs=0.1)
    assert jg['pairs'][1]['max_abs_flush_mm'] == pytest.approx(0.5, abs=0.1)

    # Wedge gap (12 mm), flush bad (3.5 mm), and too-tight (0.5 mm) all FAIL seams.py
    bad_cfg = write_json(tmp_path / 'seams_bad.json', {
        'pairs': [
            {'a': 'hood', 'b': 'fender_wedge'},
            {'a': 'hood', 'b': 'cowl_flush_bad'},
            {'a': 'hatch', 'b': 'quarter_tight'},
        ]
    })
    out_bad = tmp_path / 'seams_bad'
    r_bad = run_blender(blender, scenes['seams_test'], 'seams.py', '--project', project,
                        '--seams', bad_cfg, '--out', out_bad)
    assert r_bad.returncode == 1, r_bad.stdout[-2000:] + r_bad.stderr[-2000:]
    jb = {p['b']: p for p in read_json(out_bad / 'seams.json')['pairs']}
    assert jb['fender_wedge']['gap_passed'] is False and jb['fender_wedge']['max_gap_mm'] > 10.0
    assert jb['cowl_flush_bad']['flush_passed'] is False and jb['cowl_flush_bad']['max_abs_flush_mm'] > 3.0
    assert jb['quarter_tight']['gap_passed'] is False and jb['quarter_tight']['min_gap_mm'] < 1.0

    # Extended seating.py picks up --seam-pair and reports seams in seating.json
    out_seat = tmp_path / 'seating_ext'
    r_seat = run_blender(blender, scenes['seams_test'], 'seating.py', '--project', project,
                         '--seam-pair', 'hood:front_bumper,hatch_glass:hatch', '--out', out_seat)
    assert r_seat.returncode == 0, r_seat.stdout[-2000:] + r_seat.stderr[-2000:]
    js = read_json(out_seat / 'seating.json')
    assert js['passed'] is True and len(js['seams']) == 2
