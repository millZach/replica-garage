"""mask_photo.py, compare.py and annotate.py on drawn pictures."""
import os

import numpy as np
from PIL import Image, ImageDraw

from conftest import read_json, run_tool, write_json

W, H = 400, 250


def silhouette(dx=0, dy=0, size=(W, H)):
    """A drawn side view of a small car shape: body, cabin and two wheels."""
    m = Image.new('L', size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([60 + dx, 110 + dy, 340 + dx, 175 + dy], radius=18, fill=255)
    d.polygon([(130 + dx, 112 + dy), (175 + dx, 70 + dy), (265 + dx, 70 + dy), (300 + dx, 112 + dy)], fill=255)
    for cx in (110, 290):
        d.ellipse([cx - 30 + dx, 150 + dy, cx + 30 + dx, 210 + dy], fill=255)
    return m


def photo_of(mask, noise=2.0, seed=0, bg=(205, 208, 210), car=(40, 44, 52)):
    rng = np.random.default_rng(seed)
    m = np.asarray(mask) > 127
    img = np.empty(m.shape + (3,), float)
    img[:] = bg
    img[m] = car
    img += rng.normal(0, noise, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def render_of(mask):
    m = np.asarray(mask) > 127
    rgba = np.zeros(m.shape + (4,), np.uint8)
    rgba[m] = (150, 150, 150, 255)
    return Image.fromarray(rgba, 'RGBA')


# ------------------------------------------------------------------ mask_photo

def test_mask_photo_pass(project):
    sil = silhouette()
    p = project / 'refs' / 'photos' / 'side.jpg'
    photo_of(sil).save(p, quality=95)
    r = run_tool('mask_photo.py', p)
    assert r.returncode == 0, r.stdout + r.stderr
    m = np.asarray(Image.open(project / 'refs' / 'masks' / 'side.png')) > 127
    truth = np.asarray(sil) > 127
    assert (m ^ truth).mean() < 0.01
    assert os.path.isfile(project / 'refs' / 'masks' / 'side-preview.jpg')
    assert read_json(project / 'refs' / 'masks' / 'side.json')['passed'] is True


def test_mask_photo_gate_fails_when_vehicle_is_cut_off(project):
    p = project / 'refs' / 'photos' / 'cut.png'
    photo_of(silhouette(dx=-80)).save(p)
    r = run_tool('mask_photo.py', p)
    assert r.returncode == 1, r.stdout + r.stderr
    res = read_json(project / 'refs' / 'masks' / 'cut.json')
    assert res['checks']['inside_picture'] is False


def test_mask_photo_bad_input(project, tmp_path):
    assert run_tool('mask_photo.py').returncode == 2
    junk = tmp_path / 'junk.jpg'
    junk.write_text('not a picture', encoding='utf-8')
    assert run_tool('mask_photo.py', junk).returncode == 2
    assert run_tool('mask_photo.py', tmp_path / 'missing.jpg').returncode == 2


# ------------------------------------------------------------------ compare

def setup_compare(project, shift):
    sil = silhouette()
    photo_of(sil).save(project / 'refs' / 'photos' / 'side.jpg', quality=95)
    sil.save(project / 'refs' / 'masks' / 'side.png')
    rd = project / 'evidence' / 'round-01' / 'renders'
    os.makedirs(rd, exist_ok=True)
    # renders may be at another scale than the photo: half size here
    render_of(silhouette(dx=shift)).resize((W // 2, H // 2), Image.Resampling.LANCZOS).save(rd / 'side.png')
    return rd


def compare_args(project, rd):
    return ['--photos', project / 'refs' / 'photos', '--masks', project / 'refs' / 'masks', '--renders', rd,
            '--out', project / 'evidence' / 'round-01', '--views', 'side']


def test_compare_pass(project):
    rd = setup_compare(project, shift=0)
    r = run_tool('compare.py', *compare_args(project, rd), '--ref-width', W)
    assert r.returncode == 0, r.stdout + r.stderr
    out = read_json(project / 'evidence' / 'round-01' / 'outline.json')
    v = out['views']['side']
    assert v['median_px'] <= 1.5 and v['p95_px'] <= 3.0
    assert v['median_px_ref'] == v['median_px']           # ref width equals the photo width here
    b = Image.open(project / 'evidence' / 'round-01' / 'boards' / 'side.jpg')
    assert b.width > 3 * 600


def test_compare_gate_fails_on_offset_render(project):
    rd = setup_compare(project, shift=14)
    r = run_tool('compare.py', *compare_args(project, rd))
    assert r.returncode == 1, r.stdout + r.stderr
    v = read_json(project / 'evidence' / 'round-01' / 'outline.json')['views']['side']
    assert v['passed'] is False
    # 14 px at 400 px width is 56 px at the 1600 px reference width
    assert v['p95_px_ref'] > 30


def test_compare_bad_input(project):
    rd = setup_compare(project, shift=0)
    Image.open(rd / 'side.png').convert('RGB').save(rd / 'side.png')        # no alpha: no silhouette
    r = run_tool('compare.py', *compare_args(project, rd))
    assert r.returncode == 2 and 'alpha' in r.stderr
    assert run_tool('compare.py').returncode == 2


# ------------------------------------------------------------------ annotate

def test_annotate_pass(tmp_path):
    src = tmp_path / 'in.png'
    photo_of(silhouette()).save(src)
    marks = write_json(tmp_path / 'marks.json', {'marks': [
        {'n': 1, 'box': [60, 100, 160, 180]},
        {'n': 2, 'ellipse': [250, 60, 320, 120], 'color': '#2d7dff'},
        {'outline': [[100, 200], [200, 210], [300, 200]], 'closed': False, 'label': 'sill'}]})
    r = run_tool('annotate.py', src, tmp_path / 'out.png', marks)
    assert r.returncode == 0, r.stdout + r.stderr
    out = Image.open(tmp_path / 'out.png')
    assert out.size == (W, H)
    a = np.asarray(out).astype(int)
    assert (np.abs(a - np.asarray(Image.open(src).convert('RGB')).astype(int)).sum(2) > 60).any()
    res = read_json(str(tmp_path / 'out.png') + '.json')
    assert [m['n'] for m in res['marks']] == [1, 2, 3] and res['passed'] is True


def test_annotate_gate_fails_for_marks_outside(tmp_path):
    src = tmp_path / 'in.png'
    photo_of(silhouette()).save(src)
    marks = write_json(tmp_path / 'marks.json', [{'n': 1, 'box': [300, 200, 900, 600]}])
    r = run_tool('annotate.py', src, tmp_path / 'out.png', marks)
    assert r.returncode == 1, r.stdout + r.stderr
    assert read_json(str(tmp_path / 'out.png') + '.json')['marks'][0]['inside'] is False


def test_annotate_bad_input(tmp_path):
    src = tmp_path / 'in.png'
    photo_of(silhouette()).save(src)
    for spec in ({'scale': 0.5, 'marks': [{'box': [1, 1, 5, 5]}]},
                 [{'n': 1, 'triangle': [1, 2, 3]}],
                 [{'n': 1, 'box': [1, 2, 3]}],
                 []):
        marks = write_json(tmp_path / 'marks.json', spec)
        assert run_tool('annotate.py', src, tmp_path / 'out.png', marks).returncode == 2, spec
    assert run_tool('annotate.py').returncode == 2
