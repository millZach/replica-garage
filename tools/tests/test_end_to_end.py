"""End to end: a tiny project of three modules built through the kit, assembled, then measured."""
import hashlib
import os

import pytest

from conftest import read_json, run_blender, write_json

pytestmark = pytest.mark.blender

BODY = '''import bmesh
import bpy
import math


def build(ctx):
    d = ctx.dimensions
    x0, x1 = -d['overhang_front'], d['length'] - d['overhang_front']
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:                      # a unit cube stretched to the body's size, 150 mm off the ground
        v.co.x = ctx.mm(x0 + (v.co.x + 0.5) * (x1 - x0))
        v.co.y = ctx.mm(v.co.y * d['width'])
        v.co.z = ctx.mm(150 + (v.co.z + 0.5) * (d['height'] - 150))
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True)
    me = bpy.data.meshes.new('shell')
    bm.to_mesh(me)
    bm.free()
    shell = bpy.data.objects.new('shell', me)
    shell.data.materials.append(ctx.material('body'))
    ctx.add(shell, part='body shell', panel=True)
    me.calc_loop_triangles()
    faces = {}
    for p in me.polygons:
        for k in p.edge_keys:
            faces.setdefault(k, []).append(p.normal.copy())
    ctx.crease(shell, [k for k, n in faces.items() if len(n) == 2 and n[0].angle(n[1]) > math.radians(45)])
'''

WHEELS = '''import bmesh
import bpy
import math
from mathutils import Matrix


def build(ctx):
    d = ctx.dimensions
    for corner in ('fl', 'fr', 'rl', 'rr'):
        front = corner[0] == 'f'
        r = ctx.mm(d['tyre_diameter_front' if front else 'tyre_diameter_rear']) / 2
        w = ctx.mm(d['tyre_width_front' if front else 'tyre_width_rear'])
        y = ctx.mm(d['track_front' if front else 'track_rear']) / 2 * (-1 if corner[1] == 'l' else 1)
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=w)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'))
        me = bpy.data.meshes.new('wheel_' + corner)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new('wheel_' + corner, me)
        ob.location = (0.0 if front else ctx.mm(d['wheelbase']), y, r)
        ob.data.materials.append(ctx.material('tyre'))
        ctx.add(ob, part='wheel_' + corner)
        if front:
            ctx.steerable(ob, 'left' if corner[1] == 'l' else 'right')
'''

LAMP = '''import bpy


def build(ctx):
    loc, nor, _ = ctx.body.hit(ctx.mm([-3000, 0, 700]), (1, 0, 0))     # the nose, straight ahead of the lamp
    x = loc.x - ctx.mm(1)                                                 # seated 1 mm proud
    me = bpy.data.meshes.new('lamp')
    me.from_pydata([(x, -0.2, 0.6), (x, 0.2, 0.6), (x, 0.2, 0.8), (x, -0.2, 0.8)], [], [(0, 3, 2, 1)])
    lamp = bpy.data.objects.new('lamp', me)
    lamp.data.materials.append(ctx.material('glass'))
    ctx.add(lamp, part='lamp')
'''


def accept(project, assembly, code, depends=()):
    d = project / 'accepted' / assembly / '00'
    os.makedirs(d, exist_ok=True)
    (d / (assembly + '.py')).write_bytes(code.encode('utf-8'))
    write_json(d / 'manifest.json', {'assembly': assembly, 'version': 0, 'depends_on': list(depends),
                                     'sha256': hashlib.sha256(code.encode('utf-8')).hexdigest()})


def test_assemble_then_measure(blender, project):
    accept(project, 'body', BODY)
    accept(project, 'hardware', WHEELS)
    accept(project, 'front', LAMP, depends=['body'])
    write_json(project / 'data' / 'build.json', [
        {'assembly': 'body', 'version': 0, 'seats': []},
        {'assembly': 'hardware', 'version': 0, 'seats': []},
        {'assembly': 'front', 'version': 0, 'seats': [{'part': 'lamp', 'on': 'body shell'}]}])
    write_json(project / 'data' / 'finishes.json', {'proof_look': 'white', 'looks': {'white': {
        'studio': 'gloss', 'slots': {'body': {'base_color': [0.8, 0.8, 0.79], 'roughness': 0.3, 'coat': 1.0},
                                     'tyre': {'base_color': [0.02, 0.02, 0.02], 'roughness': 0.8},
                                     'glass': {'transmission': 1.0, 'ior': 1.5}}}}})
    r = run_blender(blender, None, 'assemble.py', '--project', project)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    out = project / 'out' / 'vehicle.blend'
    assert out.is_file()
    log = read_json(str(out) + '.json')
    assert [s['assembly'] for s in log['steps']] == ['body', 'hardware', 'front']

    ev = project / 'evidence' / 'round-01'
    r = run_blender(blender, out, 'dimensions.py', '--project', project, '--out', ev)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    dims = read_json(ev / 'dimensions.json')['dimensions']
    for k in ('length', 'width', 'height', 'wheelbase', 'track_front', 'track_rear', 'overhang_front'):
        assert dims[k]['judged'] and abs(dims[k]['error_mm']) <= 1.5, (k, dims[k])   # the lamp stands 1 mm proud

    r = run_blender(blender, out, 'fairness.py', '--project', project, '--out', ev)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    panel = read_json(ev / 'fairness.json')['panels']['shell']
    assert panel['part'] == 'body shell' and panel['crease_edges'] > 0 and panel['max_deg'] < 1.0
