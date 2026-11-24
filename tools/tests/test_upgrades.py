"""Tests for multi-scale fairness, exterior coverage, locked poses, resume, rg_seat, interfaces,
procedural surfaces, details.py and showroom.py in headless Blender."""
import os
import time

import numpy as np
import pytest
from PIL import Image

from conftest import (OrthoCamera, camera_at, camera_entry, read_json, run_blender, run_tool, write_json)

pytestmark = pytest.mark.blender


def test_render_views_trial_odd_dimensions_and_resume(blender, scenes, project):
    """--trial with odd-pixel perspective and orthographic images keeps projection_error_px < 0.5;
    --resume skips valid existing renders."""
    cams = {
        'persp_odd': camera_at((-5200.0, -4600.0, 1700.0), f=150.0, w=161, h=101, cx=82.0, cy=49.0),
        'ortho_odd': OrthoCamera([1200.0, -20000.0, 650.0], np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]]),
                                 0.03, 80.0, 30.0, 161, 61),
    }
    write_json(project / 'data' / 'cameras.json', {'cameras': {k: camera_entry(c) for k, c in cams.items()}})
    out = project / 'out' / 'trial_odd'
    r = run_blender(blender, scenes['plain'], 'render_views.py', '--project', project, '--out', out,
                    '--mode', 'clay', '--trial')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    res = read_json(out / 'render_views.json')
    for v in ('persp_odd', 'ortho_odd'):
        assert res['views'][v]['projection_error_px'] < 0.5, (v, res['views'][v])
        assert res['views'][v]['passed'] is True
    p_png = out / 'persp_odd.png'
    mtime0 = os.path.getmtime(p_png)
    time.sleep(0.05)
    r2 = run_blender(blender, scenes['plain'], 'render_views.py', '--project', project, '--out', out,
                     '--mode', 'clay', '--trial', '--resume')
    assert r2.returncode == 0, r2.stdout[-3000:] + r2.stderr[-3000:]
    res2 = read_json(out / 'render_views.json')
    assert res2['views']['persp_odd']['resumed'] is True
    assert os.path.getmtime(p_png) == mtime0


def test_fairness_wave_catches_smooth_dent_and_passes_clean_curve(blender, scenes, project, tmp_path):
    """Multi-scale quadratic waviness passes a tight smooth curve and fails a finely subdivided smooth S-ripple
    even when adjacent-face dihedral angle stays under 5 degrees."""
    r = run_blender(blender, scenes['wave_bad'], 'fairness.py', '--project', project, '--out', tmp_path)
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-3000:]
    panels = read_json(tmp_path / 'fairness.json')['panels']
    assert panels['panel_curved']['passed'] is True
    assert panels['panel_curved']['wave_mm'] <= 1.0
    dent = panels['panel_dented']
    assert dent['max_deg'] < 5.0                     # adjacent-face angle alone would have missed this!
    assert dent['wave_mm'] > 1.0 and dent['passed'] is False
    assert dent['wave_at_mm'] is not None


def test_closeups_and_orbit_exterior_filter_poses_from_and_resume(blender, scenes, project, tmp_path):
    """Internal exterior=False parts do not break exterior coverage; --poses-from replays stations; --resume skips."""
    c1 = tmp_path / 'close1'
    r = run_blender(blender, scenes['cabin'], 'closeups.py', '--project', project, '--out', c1,
                    '--size-mm', 1500, '--resolution', 16, '--samples', 1, '--samples-surface', 400)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    j1 = read_json(c1 / 'closeups.json')
    assert j1['passed'] is True
    assert all(reg['fraction'] >= 0.95 for reg in j1['coverage'].values())
    # Replay exact poses from c1 into c2, then resume c2
    c2 = tmp_path / 'close2'
    r2 = run_blender(blender, scenes['cabin'], 'closeups.py', '--project', project, '--out', c2,
                     '--poses-from', c1 / 'closeups.json', '--resolution', 16, '--samples', 1,
                     '--samples-surface', 400)
    assert r2.returncode == 0, r2.stdout[-3000:] + r2.stderr[-3000:]
    j2 = read_json(c2 / 'closeups.json')
    assert [v['name'] for v in j2['views']] == [v['name'] for v in j1['views']]
    assert j2['views'][0]['camera_mm'] == pytest.approx(j1['views'][0]['camera_mm'], abs=1e-3)
    r2_res = run_blender(blender, scenes['cabin'], 'closeups.py', '--project', project, '--out', c2,
                         '--poses-from', c1 / 'closeups.json', '--resolution', 16, '--samples', 1,
                         '--samples-surface', 400, '--resume')
    assert r2_res.returncode == 0, r2_res.stdout[-3000:] + r2_res.stderr[-3000:]
    assert all(v['resumed'] for v in read_json(c2 / 'closeups.json')['views'])

    # Orbit on cabin: exterior=False ignored so both sides reach >= 95%; --poses-from + --resume works
    o1 = tmp_path / 'orbit1'
    ro = run_blender(blender, scenes['cabin'], 'orbit.py', '--project', project, '--out', o1,
                     '--resolution', '48x32', '--samples', 1, '--samples-surface', 400)
    assert ro.returncode == 0, ro.stdout[-3000:] + ro.stderr[-3000:]
    oj1 = read_json(o1 / 'orbit.json')
    assert oj1['coverage']['left']['fraction'] >= 0.95 and oj1['coverage']['right']['fraction'] >= 0.95
    o2 = tmp_path / 'orbit2'
    ro2 = run_blender(blender, scenes['cabin'], 'orbit.py', '--project', project, '--out', o2,
                      '--poses-from', o1 / 'orbit.json', '--views', 'front-left,rear-right',
                      '--resolution', '48x32', '--samples', 1, '--samples-surface', 400)
    assert ro2.returncode == 0, ro2.stdout[-3000:] + ro2.stderr[-3000:]
    oj2 = read_json(o2 / 'orbit.json')
    assert [v['name'] for v in oj2['views']] == ['front-left', 'rear-right']
    fl1 = [v for v in oj1['views'] if v['name'] == 'front-left'][0]
    assert oj2['views'][0]['camera_mm'] == pytest.approx(fl1['camera_mm'], abs=1e-3)
    ro3 = run_blender(blender, scenes['cabin'], 'orbit.py', '--project', project, '--out', o2,
                      '--poses-from', o1 / 'orbit.json', '--views', 'front-left,rear-right',
                      '--resolution', '48x32', '--samples', 1, '--samples-surface', 400, '--resume')
    assert ro3.returncode == 0, ro3.stdout[-3000:] + ro3.stderr[-3000:]
    assert all(v['resumed'] for v in read_json(o2 / 'orbit.json')['views'])


def test_seating_auto_detects_rg_seat_on_closed_part(blender, scenes, project, tmp_path):
    """A closed solid part with ctx.seat_edge() auto-selects rg_seat without --edge-group."""
    r = run_blender(blender, scenes['seat_closed'], 'seating.py', '--project', project,
                    '--part', 'lamp_closed', '--on', 'bumper', '--out', tmp_path)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    s = read_json(tmp_path / 'seating.json')['seats'][0]
    assert s['edge_source'] == 'rg_seat'
    assert s['max_abs_step_mm'] == pytest.approx(2.0, abs=0.25) and s['passed'] is True


def test_kit_interfaces_surfaces_and_color_management(blender, project, tmp_path):
    """ctx.publish_interface / ctx.interface hand off data between assemblies; all 6 procedural surfaces and
    color_management build and render cleanly in Blender."""
    src = project / 'src'
    os.makedirs(src, exist_ok=True)
    (src / 'body.py').write_text(
        'import bpy\n'
        'def _box(n, x0, x1, y0, y1, z0, z1):\n'
        '    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]\n'
        '    f = [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)]\n'
        '    me = bpy.data.meshes.new(n); me.from_pydata(v, [], f); me.update()\n'
        '    return bpy.data.objects.new(n, me)\n'
        'def build(ctx):\n'
        '    for i, slot in enumerate(("leather", "perforated", "brushed", "carbon", "fabric", "rubber")):\n'
        '        ob = _box("p_" + slot, i * 0.3, i * 0.3 + 0.25, -0.4, 0.4, 0.2, 0.6)\n'
        '        ob.data.materials.append(ctx.material(slot))\n'
        '        ctx.add(ob, part="p_" + slot, panel=(i == 0))\n'
        '    ctx.publish_interface("sill", {"z_mm": 200.0, "y_mm": 400.0})\n',
        encoding='utf-8',
    )
    (src / 'cabin.py').write_text(
        'import bpy\n'
        'def build(ctx):\n'
        '    sill = ctx.interface("sill")\n'
        '    assert sill["z_mm"] == 200.0\n'
        '    z0 = ctx.mm(sill["z_mm"])\n'
        '    v = [(0.1, -0.2, z0), (0.3, -0.2, z0), (0.3, 0.2, z0), (0.1, 0.2, z0)]\n'
        '    me = bpy.data.meshes.new("floor"); me.from_pydata(v, [], [(0,1,2,3)]); me.update()\n'
        '    ob = bpy.data.objects.new("floor", me)\n'
        '    ob.data.materials.append(ctx.material("fabric"))\n'
        '    ctx.add(ob, part="floor", exterior=False)\n',
        encoding='utf-8',
    )
    assert run_tool('accept.py', 'body', '0', '--project', project).returncode == 0
    assert run_tool('accept.py', 'cabin', '0', '--project', project, '--depends-on', 'body').returncode == 0
    write_json(project / 'data' / 'finishes.json', {
        'proof_look': 'spec',
        'end_fill_watts': 35,
        'showroom': {'card_watts': 260, 'floor_roughness': 0.14},
        'color_management': {'view_transform': 'AgX', 'look': 'None', 'exposure': 0.0},
        'looks': {
            'spec': {
                'studio': 'gloss',
                'slots': {
                    'leather': {'base_color': [0.06, 0.05, 0.05], 'roughness': 0.55, 'sheen': 0.2,
                                'surface': 'leather', 'bump_strength': 0.12, 'bump_scale_mm': 2.5},
                    'perforated': {'base_color': [0.04, 0.04, 0.04], 'roughness': 0.6, 'surface': 'perforated'},
                    'brushed': {'base_color': [0.6, 0.6, 0.62], 'metallic': 1.0, 'roughness': 0.3,
                                'anisotropic': 0.5, 'surface': 'brushed'},
                    'carbon': {'base_color': [0.05, 0.05, 0.05], 'roughness': 0.25, 'coat': 1.0,
                               'surface': 'carbon'},
                    'fabric': {'base_color': [0.08, 0.08, 0.09], 'roughness': 0.85, 'sheen': 0.4,
                               'surface': 'fabric'},
                    'rubber': {'base_color': [0.03, 0.03, 0.03], 'roughness': 0.78, 'surface': 'rubber'},
                },
            }
        },
    })
    blend = project / 'out' / 'vehicle.blend'
    r = run_blender(blender, None, 'assemble.py', '--project', project, '--out', blend)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    # Render an orbit frame to verify every procedural node tree and showroom tuning renders in Cycles
    r_orb = run_blender(blender, blend, 'orbit.py', '--project', project, '--out', tmp_path / 'orb',
                        '--views', 'front-left', '--resolution', '48x32', '--samples', 1, '--samples-surface', 200)
    assert r_orb.returncode == 0, r_orb.stdout[-3000:] + r_orb.stderr[-3000:]
    assert os.path.isfile(tmp_path / 'orb' / 'front-left.png')


def test_details_cutaway_interior_ab_strip_and_sightlines(blender, scenes, project, tmp_path):
    """details.py handles cutaway hide (restored after), interior lighting, toggle_part A/B, strip-sweep,
    ray sightline visibility (--fail-on-occluded) and --resume."""
    spec = write_json(project / 'data' / 'details.json', [
        {
            'name': 'cabin_open',
            'camera_mm': [1800.0, -300.0, 2100.0],
            'target_mm': [800.0, 0.0, 750.0],
            'lens_mm': 35.0,
            'resolution': [48, 36],
            'lighting': 'interior',
            'hide': ['roof'],
            'denoise': False,
            'toggle_part': 'seat',
            'targets_mm': {
                'dash_face': [700.0, 0.0, 750.0],
                'behind_dash': [200.0, 0.0, 750.0],
            },
        },
        {
            'name': 'cabin_closed',
            'camera_mm': [1800.0, -300.0, 2100.0],
            'target_mm': [800.0, 0.0, 750.0],
            'lens_mm': 35.0,
            'resolution': [48, 36],
            'lighting': 'style',
            'targets_mm': {
                'dash_blocked_by_roof': [700.0, 0.0, 750.0],
            },
        },
        {
            'name': 'side_strip',
            'camera_mm': [1200.0, -3500.0, 900.0],
            'target_mm': [1200.0, -900.0, 700.0],
            'lens_mm': 50.0,
            'resolution': [48, 36],
            'lighting': 'strip-sweep',
            'strip_angles_deg': [-15.0, 15.0],
        },
    ])
    out = tmp_path / 'details'
    # With --fail-on-occluded, cabin_open's behind_dash and cabin_closed's dash_blocked_by_roof are occluded -> exit 1
    r = run_blender(blender, scenes['cabin'], 'details.py', '--project', project, '--spec', spec,
                    '--out', out, '--samples', 1, '--fail-on-occluded')
    assert r.returncode == 1, r.stdout[-3000:] + r.stderr[-3000:]
    j = read_json(out / 'details.json')
    by_name = {v['name']: v for v in j['views']}
    v_open = by_name['cabin_open']
    assert v_open['sightlines']['dash_face']['visible'] is True
    assert v_open['sightlines']['behind_dash']['visible'] is False
    assert os.path.isfile(out / 'cabin_open.png') and os.path.isfile(out / 'cabin_open-without-seat.png')
    # Proof that roof visibility was restored after cabin_open finished:
    v_closed = by_name['cabin_closed']
    assert v_closed['sightlines']['dash_blocked_by_roof']['visible'] is False
    assert v_closed['sightlines']['dash_blocked_by_roof']['first_hit']['part'] == 'roof'
    # Strip-sweep wrote both angle images
    assert len(by_name['side_strip']['files']) == 2
    assert all(os.path.isfile(f['file']) for f in by_name['side_strip']['files'])
    # --resume skips existing renders and exits 0 without --fail-on-occluded
    r2 = run_blender(blender, scenes['cabin'], 'details.py', '--project', project, '--spec', spec,
                     '--out', out, '--samples', 1, '--resume')
    assert r2.returncode == 0, r2.stdout[-3000:] + r2.stderr[-3000:]
    j2 = {v['name']: v for v in read_json(out / 'details.json')['views']}
    assert all(f['resumed'] for f in j2['cabin_open']['files'])
    assert all(f['resumed'] for f in j2['side_strip']['files'])


def test_showroom_saves_blend_and_handoff(blender, scenes, project, tmp_path):
    """showroom.py saves a ready-to-open .blend with framing camera, look, color management and handoff JSON."""
    write_json(project / 'data' / 'finishes.json', {
        'proof_look': 'hero',
        'style': 'showroom',
        'color_management': {'view_transform': 'AgX', 'look': 'None', 'exposure': 0.05},
        'looks': {
            'hero': {
                'studio': 'gloss',
                'slots': {
                    'body': {'base_color': [0.8, 0.1, 0.1], 'roughness': 0.2, 'coat': 1.0},
                    'tyre': {'base_color': [0.02, 0.02, 0.02], 'roughness': 0.8},
                    'drl': {'base_color': [1.0, 1.0, 1.0], 'emission': [1.0, 1.0, 1.0], 'emission_strength': 8.0},
                },
            }
        },
    })
    out_blend = tmp_path / 'vehicle-showroom.blend'
    handoff = project / 'data' / 'handoff.json'
    r = run_blender(blender, scenes['car'], 'showroom.py', '--project', project,
                    '--out', out_blend, '--handoff', handoff, '--resolution', '320x180')
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert out_blend.is_file() and handoff.is_file()
    h = read_json(handoff)
    assert h['source_blend'] != h['showroom_blend']
    assert h['look'] == 'hero' and h['style'] == 'showroom'
    assert set(h['steerable'].keys()) == {'wheel_fl', 'wheel_fr'}
    assert h['emissive_slots'] == ['drl']
    assert h['camera']['name'] == 'front-left' and h['camera']['resolution'] == [320, 180]
    # Verify the saved showroom .blend opens cleanly in Blender and has an active camera + Cycles configured
    check = run_blender(blender, out_blend, 'dimensions.py', '--project', project, '--out', tmp_path / 'dims')
    assert check.returncode == 0, check.stdout[-3000:] + check.stderr[-3000:]


def test_new_tools_usage_on_no_args(blender, scenes):
    assert run_tool('accept.py').returncode == 2
    for t in ('details.py', 'showroom.py'):
        r = run_blender(blender, scenes['plain'], t)
        assert r.returncode == 2 and 'usage' in r.stdout, (t, r.stdout, r.stderr)
