"""mask_photo.py, compare.py and annotate.py on drawn pictures."""
import os

import numpy as np
from PIL import Image, ImageDraw

from conftest import Camera, camera_entry, landmark_entry, read_json, run_tool, write_json

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


def photo_of(mask, noise=2.0, seed=0, bg=(205, 208, 210), car=(40, 44, 52), busy=False):
    rng = np.random.default_rng(seed)
    m = np.asarray(mask) > 127
    img = np.empty(m.shape + (3,), float)
    img[:] = bg
    if busy:                                   # a cluttered background of coloured blocks
        for _ in range(60):
            x, y = rng.integers(0, m.shape[1] - 20), rng.integers(0, m.shape[0] - 20)
            img[y:y + rng.integers(8, 40), x:x + rng.integers(8, 60)] = rng.integers(120, 255, 3)
    img[m] = car
    img += rng.normal(0, noise, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def render_of(mask):
    m = np.asarray(mask) > 127
    rgba = np.zeros(m.shape + (4,), np.uint8)
    rgba[m] = (150, 150, 150, 255)
    return Image.fromarray(rgba, 'RGBA')


def landmarks(project, entries):
    write_json(project / 'data' / 'landmarks.json', [landmark_entry(v, f, k, c) for v, f, k, c in entries])


# ------------------------------------------------------------------ mask_photo

def test_mask_photo_plain_background_with_crop(project):
    sil = silhouette()
    big = Image.new('RGB', (W + 100, H + 60), (90, 20, 20))       # the crop cuts this border away
    big.paste(photo_of(sil), (60, 40))
    big.save(project / 'refs' / 'photos' / 'side.jpg', quality=95)
    landmarks(project, [('side', 'refs/photos/side.jpg', 'photo', [60, 40, 60 + W, 40 + H])])
    r = run_tool('mask_photo.py', 'side', '--project', project)
    assert r.returncode == 0, r.stdout + r.stderr
    m = np.asarray(Image.open(project / 'refs' / 'masks' / 'side.png')) > 127
    assert m.shape == (H, W)
    assert (m ^ (np.asarray(sil) > 127)).mean() < 0.01
    assert os.path.isfile(project / 'refs' / 'masks' / 'side-preview.jpg')


def test_mask_photo_drawing_and_seed(project):
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.rounded_rectangle([60, 110, 340, 175], radius=18, outline=(0, 0, 0), width=2)
    sheet.save(project / 'refs' / 'photos' / 'sheet.png')
    photo_of(silhouette(), busy=True).save(project / 'refs' / 'photos' / 'busy.png')
    landmarks(project, [('elevation', 'refs/photos/sheet.png', 'drawing', None),
                        ('busy', 'refs/photos/busy.png', 'photo', None)])
    r = run_tool('mask_photo.py', 'elevation', '--project', project)
    assert r.returncode == 0, r.stdout + r.stderr
    m = np.asarray(Image.open(project / 'refs' / 'masks' / 'elevation.png')) > 127
    assert m[140, 200] and not m[50, 200] and abs(m.sum() - 280 * 65) < 0.08 * 280 * 65
    # a busy background needs a seed: a rough render of the same view (here shifted a little, at half size)
    seed = project / 'seed.png'
    render_of(silhouette(dx=4, dy=-3)).resize((W // 2, H // 2)).save(seed)
    r = run_tool('mask_photo.py', 'busy', '--project', project, '--seed', seed)
    assert r.returncode == 0, r.stdout + r.stderr
    m = np.asarray(Image.open(project / 'refs' / 'masks' / 'busy.png')) > 127
    assert (m ^ (np.asarray(silhouette()) > 127)).mean() < 0.02


def test_mask_photo_gate_fails_when_vehicle_is_cut_off(project):
    photo_of(silhouette(dx=-80)).save(project / 'refs' / 'photos' / 'cut.png')
    landmarks(project, [('cut', 'refs/photos/cut.png', 'photo', None)])
    r = run_tool('mask_photo.py', 'cut', '--project', project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert read_json(project / 'refs' / 'masks' / 'cut.json')['checks']['inside_picture'] is False


def test_mask_photo_bad_input(project):
    assert run_tool('mask_photo.py').returncode == 2
    (project / 'refs' / 'photos' / 'junk.jpg').write_text('not a picture', encoding='utf-8')
    landmarks(project, [('junk', 'refs/photos/junk.jpg', 'photo', None)])
    assert run_tool('mask_photo.py', 'junk', '--project', project).returncode == 2
    assert run_tool('mask_photo.py', 'nope', '--project', project).returncode == 2


# ------------------------------------------------------------------ compare

def setup_compare(project, shift, grade='precise'):
    sil = silhouette()
    photo_of(sil).save(project / 'refs' / 'photos' / 'side.jpg', quality=95)
    sil.save(project / 'refs' / 'masks' / 'side.png')
    cam = Camera([0.0, -9000.0, 600.0], [[1, 0, 0], [0, 0, -1], [0, 1, 0]], 500.0, (W - 1) / 2, (H - 1) / 2, W, H)
    write_json(project / 'data' / 'cameras.json', {'cameras': {'side': camera_entry(cam, grade=grade),
                                                               'top': camera_entry(cam, grade='visual')}})
    landmarks(project, [('side', 'refs/photos/side.jpg', 'photo', None),
                        ('top', 'refs/photos/side.jpg', 'photo', None)])
    rd = project / 'evidence' / 'round-01' / 'clay'
    os.makedirs(rd, exist_ok=True)
    # renders may be at another scale than the picture: half size here (a trial render)
    render_of(silhouette(dx=shift)).resize((W // 2, H // 2), Image.Resampling.LANCZOS).save(rd / 'side.png')
    render_of(silhouette(dx=40)).save(rd / 'top.png')            # far off, but a visual view does not count
    return rd


def compare(project, rd, *extra):
    return run_tool('compare.py', '--project', project, '--renders', rd, '--out', project / 'evidence' / 'round-01',
                    *extra)


def test_compare_pass_and_visual_views_do_not_count(project):
    rd = setup_compare(project, shift=0)
    r = compare(project, rd, '--ref-width', W)
    assert r.returncode == 0, r.stdout + r.stderr
    out = read_json(project / 'evidence' / 'round-01' / 'outline.json')
    v = out['views']['side']
    assert v['median_px'] <= 1.5 and v['p95_px'] <= 3.0 and v['passed'] is True
    assert out['views']['top']['counted'] is False and out['views']['top']['passed'] is None
    assert out['views']['top']['note'] == 'no mask for this view'
    assert Image.open(project / 'evidence' / 'round-01' / 'boards' / 'side.jpg').width > 3 * 600


def test_compare_gate_fails_on_offset_render(project):
    rd = setup_compare(project, shift=14)
    r = compare(project, rd)
    assert r.returncode == 1, r.stdout + r.stderr
    v = read_json(project / 'evidence' / 'round-01' / 'outline.json')['views']['side']
    assert v['passed'] is False and v['p95_px_ref'] > 30          # 14 px at 400 px is 56 px at 1600 px


def test_compare_bad_input(project):
    rd = setup_compare(project, shift=0)
    Image.open(rd / 'side.png').convert('RGB').save(rd / 'side.png')        # no alpha: no silhouette
    r = compare(project, rd)
    assert r.returncode == 2 and 'alpha' in r.stderr
    cams = read_json(project / 'data' / 'cameras.json')
    del cams['cameras']['side']['grade']
    write_json(project / 'data' / 'cameras.json', cams)
    r = compare(project, rd)
    assert r.returncode == 2 and "missing key 'grade'" in r.stderr
    assert run_tool('compare.py').returncode == 2


# ------------------------------------------------------------------ annotate

def test_annotate_pass(project):
    rnd = project / 'evidence' / 'round-01'
    os.makedirs(rnd / 'boards', exist_ok=True)
    pic = rnd / 'boards' / 'side.jpg'
    photo_of(silhouette()).save(pic)
    marks = write_json(rnd / 'marks.json', [
        {'n': 1, 'picture': 'boards/side.jpg', 'shape': 'box', 'points': [[60, 100], [160, 180]]},
        {'n': 2, 'picture': 'boards/side.jpg', 'shape': 'ellipse', 'points': [[250, 60], [320, 120]],
         'color': '#2d7dff'},
        {'n': 3, 'picture': 'boards/side.jpg', 'shape': 'outline', 'points': [[100, 200], [200, 210], [300, 200]],
         'closed': False},
        {'n': 4, 'picture': 'boards/front.jpg', 'shape': 'box', 'points': [[0, 0], [9000, 9000]]}])
    r = run_tool('annotate.py', pic, marks)
    assert r.returncode == 0, r.stdout + r.stderr
    out = Image.open(rnd / 'boards' / 'side-marked.jpg')
    assert out.size == (W, H)
    res = read_json(str(rnd / 'boards' / 'side-marked.jpg') + '.json')
    assert [m['n'] for m in res['marks']] == [1, 2, 3] and res['passed'] is True


def test_annotate_gate_fails_for_marks_outside(project):
    pic = project / 'pic.png'
    photo_of(silhouette()).save(pic)
    marks = write_json(project / 'marks.json', [{'n': 1, 'picture': 'pic.png', 'shape': 'box',
                                                 'points': [[300, 200], [900, 600]]}])
    r = run_tool('annotate.py', pic, marks, '--out', project / 'out.png')
    assert r.returncode == 1, r.stdout + r.stderr
    assert read_json(str(project / 'out.png') + '.json')['marks'][0]['inside'] is False


def test_annotate_bad_input(project):
    pic = project / 'pic.png'
    photo_of(silhouette()).save(pic)
    for spec in ([{'n': 1, 'picture': 'pic.png', 'shape': 'triangle', 'points': [[1, 2], [3, 4]]}],
                 [{'n': 1, 'picture': 'pic.png', 'shape': 'box', 'points': [[1, 2]]}],
                 [{'n': 1, 'picture': 'other.png', 'shape': 'box', 'points': [[1, 2], [3, 4]]}],
                 [{'n': 1, 'shape': 'box', 'points': [[1, 2], [3, 4]]}]):
        marks = write_json(project / 'marks.json', spec)
        assert run_tool('annotate.py', pic, marks).returncode == 2, spec
    assert run_tool('annotate.py').returncode == 2


def test_mask_photo_seed_without_opencv(project, tmp_path):
    """The seeded mask falls back to a colour model when OpenCV is not installed."""
    import subprocess
    import sys
    from conftest import ENV, TOOLS
    block = tmp_path / 'block'
    os.makedirs(block)
    (block / 'cv2.py').write_text("raise ImportError('blocked for this test')\n", encoding='utf-8')
    photo_of(silhouette(), busy=True).save(project / 'refs' / 'photos' / 'busy.png')
    landmarks(project, [('busy', 'refs/photos/busy.png', 'photo', None)])
    seed = project / 'seed.png'
    render_of(silhouette(dx=4, dy=-3)).save(seed)
    env = dict(ENV, PYTHONPATH=str(block))
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'mask_photo.py'), 'busy', '--project', str(project),
                        '--seed', str(seed)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    res = read_json(project / 'refs' / 'masks' / 'busy.json')
    assert res['segmentation'] == 'colour model'
    m = np.asarray(Image.open(project / 'refs' / 'masks' / 'busy.png')) > 127
    assert (m ^ (np.asarray(silhouette()) > 127)).mean() < 0.03


def test_mask_photo_drawing_close_px_bridges_dashed_lines(project):
    """A drawing with a dashed outline leaks flood-fill unless --close-px bridges the dashes."""
    sheet = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    # Dashed rectangle: 8 px dashes separated by 4 px gaps
    for x in range(80, 320, 12):
        d.line([(x, 80), (min(x + 7, 320), 80)], fill=(0, 0, 0), width=2)
        d.line([(x, 180), (min(x + 7, 320), 180)], fill=(0, 0, 0), width=2)
    for y in range(80, 180, 12):
        d.line([(80, y), (80, min(y + 7, 180))], fill=(0, 0, 0), width=2)
        d.line([(320, y), (320, min(y + 7, 180))], fill=(0, 0, 0), width=2)
    sheet.save(project / 'refs' / 'photos' / 'dashed.png')
    landmarks(project, [('dashed', 'refs/photos/dashed.png', 'drawing', None)])
    r_plain = run_tool('mask_photo.py', 'dashed', '--project', project)
    m_plain = np.asarray(Image.open(project / 'refs' / 'masks' / 'dashed.png')) > 127
    assert not m_plain[130, 200]                     # leaked through the dashes
    r_close = run_tool('mask_photo.py', 'dashed', '--project', project, '--close-px', 4)
    assert r_close.returncode == 0, r_close.stdout + r_close.stderr
    m_close = np.asarray(Image.open(project / 'refs' / 'masks' / 'dashed.png')) > 127
    assert m_close[130, 200] and not m_close[30, 200]
    assert read_json(project / 'refs' / 'masks' / 'dashed.json')['close_px'] == 4


def test_compare_fills_internal_holes_and_honors_ignore_mask(project):
    """Transparent windows/spokes inside the render silhouette are filled by default; -ignore.png excludes regions."""
    rd = setup_compare(project, shift=0)
    # Punch a large transparent window hole inside the render alpha
    ren = np.asarray(render_of(silhouette())).copy()
    ren[120:160, 150:250, 3] = 0
    Image.fromarray(ren, 'RGBA').save(rd / 'side.png')
    # Default: fills holes -> passes
    r_fill = compare(project, rd, '--ref-width', W)
    assert r_fill.returncode == 0, r_fill.stdout + r_fill.stderr
    assert read_json(project / 'evidence' / 'round-01' / 'outline.json')['views']['side']['p95_px'] <= 1.5
    # --keep-holes: inner hole contour creates large error -> fails
    r_holes = compare(project, rd, '--ref-width', W, '--keep-holes')
    assert r_holes.returncode == 1
    assert read_json(project / 'evidence' / 'round-01' / 'outline.json')['views']['side']['p95_px'] > 10.0

    # Now add a protruding mismatched lobe above the bonnet, then ignore that box via side-ignore.png
    ren2 = np.asarray(render_of(silhouette())).copy()
    ren2[70:115, 70:130, 3] = 255
    Image.fromarray(ren2, 'RGBA').save(rd / 'side.png')
    assert compare(project, rd, '--ref-width', W).returncode == 1
    ign = Image.new('L', (W, H), 0)
    ImageDraw.Draw(ign).rectangle([65, 65, 135, 120], fill=255)
    ign.save(project / 'refs' / 'masks' / 'side-ignore.png')
    r_ign = compare(project, rd, '--ref-width', W)
    assert r_ign.returncode == 0, r_ign.stdout + r_ign.stderr
    assert read_json(project / 'evidence' / 'round-01' / 'outline.json')['views']['side']['ignore_mask'] is not None
