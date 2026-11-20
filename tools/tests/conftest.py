"""Shared fixtures: run a tool as a subprocess, a synthetic box vehicle, synthetic cameras, headless Blender."""
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.dont_write_bytecode = True
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from _common import Camera, OrthoCamera, look_at  # noqa: E402,F401

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

# The synthetic "vehicle": a box with known dimensions (mm, vehicle coordinates).
BOX = dict(x0=-900.0, x1=3300.0, y=900.0, z0=0.0, z1=1300.0)
DIMS = dict(length=4200.0, width=1800.0, height=1300.0, wheelbase=2500.0, track_front=1560.0, track_rear=1580.0,
            overhang_front=900.0, tyre_diameter_front=660.0, tyre_diameter_rear=680.0, tyre_width_front=200.0,
            tyre_width_rear=220.0, rim_diameter_front=500.0, rim_diameter_rear=520.0)
VEHICLE = dict(maker='Synthetic', model='Box', generation='1', years='2000', trim='test', dimensions=DIMS)


def run_tool(name, *args, timeout=300):
    return subprocess.run([sys.executable, os.path.join(TOOLS, name)] + [str(a) for a in args],
                          capture_output=True, text=True, env=ENV, timeout=timeout)


def box_corners():
    b = BOX
    return {'%s%s%s' % (xn, yn, zn): [x, y, z]
            for xn, x in (('f', b['x0']), ('r', b['x1']))
            for yn, y in (('l', -b['y']), ('r', b['y']))
            for zn, z in (('b', 150.0), ('t', b['z1']))}


def camera_at(C, at=(1200.0, 0.0, 600.0), f=1400.0, w=1600, h=1000, cx=None, cy=None):
    return Camera(C, look_at(C, at), f, (w - 1) / 2 if cx is None else cx, (h - 1) / 2 if cy is None else cy, w, h)


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    return path


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def project(tmp_path):
    """A project folder with vehicle.json for the box and its folders."""
    for d in ('refs/photos', 'refs/masks', 'data', 'evidence/round-01', 'accepted'):
        os.makedirs(tmp_path / d, exist_ok=True)
    write_json(tmp_path / 'data' / 'vehicle.json', dict(VEHICLE, points=box_corners()))
    return tmp_path


def blank_picture(path, w, h, rgb=(200, 200, 200)):
    from PIL import Image
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.new('RGB', (int(w), int(h)), rgb).save(path)
    return path


# ------------------------------------------------------------------ Blender

def find_blender():
    cand = os.environ.get('BLENDER')
    if cand and os.path.isfile(cand):
        return cand
    return shutil.which('blender')


@pytest.fixture(scope='session')
def blender():
    exe = find_blender()
    if not exe:
        pytest.skip('Blender not found (set BLENDER or put blender on PATH)')
    return exe


def run_blender(exe, blend, tool, *args, timeout=600, env=None):
    cmd = [exe, '-b']
    if blend:
        cmd.append(str(blend))
    cmd += ['--factory-startup', '--python', os.path.join(TOOLS, tool), '--'] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, text=True, env=dict(ENV, **(env or {})), timeout=timeout,
                          encoding='utf-8', errors='replace')


SCENES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scenes.py')


@pytest.fixture(scope='session')
def scenes(blender, tmp_path_factory):
    """Build every small test scene in one headless Blender run; returns {name: path to .blend}."""
    out = tmp_path_factory.mktemp('scenes')
    r = subprocess.run([blender, '-b', '--factory-startup', '--python', SCENES, '--', str(out)],
                       capture_output=True, text=True, env=ENV, timeout=600, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError('scene build failed:\n' + r.stdout[-3000:] + r.stderr[-3000:])
    return {os.path.splitext(n)[0]: str(out / n) for n in os.listdir(out) if n.endswith('.blend')}


def camera_entry(cam, steer=0.0, grade='precise', rms_mm=1.0, rms_px=0.5, **extra):
    """A cameras.json entry with every key the contract lists."""
    e = cam.as_dict()
    e.update(steer_deg=steer, grade=grade, rms_mm=rms_mm, rms_px=rms_px, **extra)
    return e


def landmark_entry(view, file, kind='photo', crop=None, points=None, steer=0.0):
    e = dict(view=view, file=file, kind=kind, steer_deg=steer, points=points or {})
    if crop:
        e['crop'] = crop
    return e
