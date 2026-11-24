"""gates.py on a synthetic round folder, and wait_for.py."""
import os
import subprocess
import sys
import time

from conftest import ENV, TOOLS, camera_at, camera_entry, read_json, run_tool, write_json


def fill_round(rnd, worse=False):
    cam = camera_at((-5000.0, -4000.0, 1500.0))
    write_json(rnd / 'cameras.json', {'cameras': {
        'front-34': camera_entry(cam, rms_mm=4.0), 'rear-34': camera_entry(cam, rms_mm=6.0),
        'side': camera_entry(cam, rms_mm=2.0, planar=True, grade='visual'),
        'drawing': camera_entry(cam, rms_mm=15.0 if worse else 5.0, grade='visual' if worse else 'precise')}})
    write_json(rnd / 'dimensions.json', {'dimensions': {
        'length': {'measured_mm': 4203.0, 'maker_mm': 4200.0, 'error_mm': 3.0, 'judged': True},
        'width': {'measured_mm': 1800.0, 'maker_mm': 1800.0, 'error_mm': 0.0, 'judged': True},
        'overhang_front': {'measured_mm': 950.0, 'maker_mm': 900.0, 'error_mm': 50.0, 'judged': False}}})
    write_json(rnd / 'outline.json', {'views': {
        'front-34': {'width': 800, 'median_px': 1.0, 'p95_px': 3.0, 'grade': 'precise'},
        'side': {'width': 800, 'median_px': 9.0, 'p95_px': 30.0, 'grade': 'visual'}}})
    write_json(rnd / 'fairness.json', {'panels': {'door': {'p99_deg': 1.0, 'max_deg': 3.0}}})
    write_json(rnd / 'seating.json', {'seats': [{'part': 'lamp', 'on': 'bumper', 'max_abs_step_mm': 1.2}]})
    write_json(rnd / 'daylight.json', {'total_leaks': 0, 'background_leaks': 0, 'wedge_leaks': 0,
                                       'inner_leaks': 0, 'backface_leaks': 0, 'passed': True})
    write_json(rnd / 'rays.json', {'double_skins': 0})
    write_json(rnd / 'separation.json', {'level': 2, 'parts': [{'part': 'door', 'own_object': True,
                                                                'pivot_ok': True}],
                                         'overlaps': [{'a': 'door', 'b': 'wing', 'depth_mm': 0.2}]})


def test_gates_pass(project):
    rnd = project / 'evidence' / 'round-01'
    fill_round(rnd)
    r = run_tool('gates.py', rnd)
    assert r.returncode == 0, r.stdout + r.stderr
    g = read_json(rnd / 'gates.json')
    assert g['passed'] is True and not g['missing'] and not g['changed_limits']
    # separation is not needed without data/parts.json; the visual view's outline does not count
    assert g['summary']['separation'] == 'pass'
    assert [x for x in g['gates'] if x['item'] == 'side median'][0]['counted'] is False
    # outline at 800 px width is judged at 1600: 1 px -> 2 px
    med = [x for x in g['gates'] if x['item'] == 'front-34 median'][0]
    assert abs(med['measured'] - 2.0) < 1e-9
    assert all({'gate', 'measured', 'limit', 'passed'} <= set(x) for x in g['gates'])


def test_gates_fail_and_changed_limits(project):
    rnd = project / 'evidence' / 'round-01'
    fill_round(rnd, worse=True)
    r = run_tool('gates.py', rnd)
    assert r.returncode == 1
    g = read_json(rnd / 'gates.json')
    assert g['summary']['cameras'] == 'fail' and g['passed'] is False
    # a project can loosen a limit; the change is printed and recorded
    write_json(project / 'data' / 'limits.json', {'camera_rms_mm': 20})
    r = run_tool('gates.py', rnd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'camera_rms_mm 12 -> 20' in r.stdout
    assert read_json(rnd / 'gates.json')['changed_limits']['camera_rms_mm']['used'] == 20
    # with take-apart parts listed, separation evidence is needed: missing fails unless skipped
    write_json(project / 'data' / 'parts.json', [])
    os.remove(rnd / 'separation.json')
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['separation'] == 'missing'
    assert run_tool('gates.py', rnd, '--skip', 'separation').returncode == 0


def test_gates_bad_input(project, tmp_path):
    assert run_tool('gates.py').returncode == 2
    assert run_tool('gates.py', tmp_path / 'nope').returncode == 2
    rnd = project / 'evidence' / 'round-01'
    fill_round(rnd)
    lim = write_json(tmp_path / 'lim.json', {'no_such_limit': 1})
    assert run_tool('gates.py', rnd, '--limits', lim).returncode == 2
    (rnd / 'fairness.json').write_text('{"panels": ', encoding='utf-8')
    assert run_tool('gates.py', rnd).returncode == 2


def test_wait_for_ready(tmp_path):
    target = tmp_path / 'notes' / 'note-01.md'
    os.makedirs(target.parent)
    writer = subprocess.Popen([sys.executable, '-c',
                               'import time,sys;time.sleep(1.0);open(sys.argv[1],"w").write("go")', str(target)],
                              env=ENV)
    t0 = time.monotonic()
    r = run_tool('wait_for.py', target, 20, '--settle', 0.5, '--interval', 0.1, '--print')
    writer.wait()
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"ready"' in r.stdout and 'go' in r.stdout
    assert time.monotonic() - t0 < 15


def test_wait_for_timeout(tmp_path):
    r = run_tool('wait_for.py', tmp_path / 'never.md', 0.5, '--interval', 0.1)
    assert r.returncode == 1 and 'absent' in r.stdout


def test_wait_for_bad_input(tmp_path):
    assert run_tool('wait_for.py').returncode == 2
    assert run_tool('wait_for.py', tmp_path, 1).returncode == 2
    assert run_tool('wait_for.py', tmp_path / 'x', -1).returncode == 2
    assert os.path.isfile(os.path.join(TOOLS, 'wait_for.py'))


def test_gates_frozen_cameras_dedupe_seating_wave_and_visual_unmasked(project):
    rnd = project / 'evidence' / 'round-01'
    fill_round(rnd)
    # Put a failing cameras.json in data/ while round has passing cameras.json: round must win
    cam = camera_at((-5000.0, -4000.0, 1500.0))
    write_json(project / 'data' / 'cameras.json', {'cameras': {
        'only': camera_entry(cam, rms_mm=99.0, grade='visual')}})
    # Add a duplicate seating record in a second seating file
    write_json(rnd / 'seating-extra.json', {'seats': [
        {'part': 'lamp', 'on': 'bumper', 'max_abs_step_mm': 1.2},
        {'part': 'mirror', 'on': 'door', 'max_abs_step_mm': 1.5}]})
    # Unmasked visual view in outline.json should NOT be marked failed
    write_json(rnd / 'outline.json', {'views': {
        'front-34': {'width': 800, 'median_px': 1.0, 'p95_px': 3.0, 'grade': 'precise', 'counted': True},
        'side': {'width': 800, 'grade': 'visual', 'counted': False, 'passed': None, 'note': 'no mask for this view'}}})
    r = run_tool('gates.py', rnd)
    assert r.returncode == 0, r.stdout + r.stderr
    g = read_json(rnd / 'gates.json')
    seat_items = [x['item'] for x in g['gates'] if x['gate'] == 'seating']
    assert seat_items == ['lamp on bumper', 'mirror on door']
    vis = [x for x in g['gates'] if x['gate'] == 'outline' and x['item'] == 'side'][0]
    assert vis['counted'] is False and vis['passed'] is True
    # Now fail on fairness_wave_mm (default 1.0 mm), then loosen limit and pass
    write_json(rnd / 'fairness.json', {'panels': {'door': {'p99_deg': 1.0, 'max_deg': 2.0, 'wave_mm': 2.4}}})
    assert run_tool('gates.py', rnd).returncode == 1
    assert read_json(rnd / 'gates.json')['summary']['fairness'] == 'fail'
    write_json(project / 'data' / 'limits.json', {'fairness_wave_mm': 3.0})
    assert run_tool('gates.py', rnd).returncode == 0


def test_accept_freezes_manifest_updates_builds_and_guards_overwrite(project):
    assert run_tool('accept.py').returncode == 2
    src = project / 'src'
    os.makedirs(src, exist_ok=True)
    (src / 'body.py').write_text('def build(ctx):\n    pass\n', encoding='utf-8')
    (src / 'front.py').write_text('def build(ctx):\n    pass\n', encoding='utf-8')
    # Pre-create a workshop build list containing only body (not front)
    ws = write_json(project / 'data' / 'build-workshop.json', [
        {'assembly': 'body', 'version': 0, 'seats': []}])
    seats = write_json(project / 'seats_front.json', [{'part': 'lamp', 'on': 'bumper'}])
    r = run_tool('accept.py', 'body', '1', '--project', project, '--also-build', ws)
    assert r.returncode == 0, r.stdout + r.stderr
    acc_mod = project / 'accepted' / 'body' / '01' / 'body.py'
    man = read_json(project / 'accepted' / 'body' / '01' / 'manifest.json')
    assert acc_mod.is_file() and man['assembly'] == 'body' and man['version'] == 1 and len(man['sha256']) == 64
    assert read_json(project / 'data' / 'build.json') == [{'assembly': 'body', 'version': 1, 'seats': []}]
    assert read_json(ws) == [{'assembly': 'body', 'version': 1, 'seats': []}]
    # Accept front with depends-on and seats: added to build.json, NOT added to workshop list since absent there
    r2 = run_tool('accept.py', 'front', '0', '--project', project, '--depends-on', 'body',
                  '--seats', seats, '--also-build', ws)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert len(read_json(ws)) == 1
    assert read_json(project / 'data' / 'build.json')[1] == {
        'assembly': 'front', 'version': 0, 'seats': [{'part': 'lamp', 'on': 'bumper'}]}
    assert read_json(project / 'accepted' / 'front' / '00' / 'manifest.json')['depends_on'] == ['body']
    # Modifying src/body.py and re-accepting version 1 refuses without --force, succeeds with --force
    (src / 'body.py').write_text('def build(ctx):\n    return 1\n', encoding='utf-8')
    assert run_tool('accept.py', 'body', '1', '--project', project).returncode == 2
    assert run_tool('accept.py', 'body', '1', '--project', project, '--force').returncode == 0
    assert read_json(project / 'accepted' / 'body' / '01' / 'manifest.json')['sha256'] != man['sha256']
