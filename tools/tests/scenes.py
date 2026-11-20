"""Build the small synthetic test scenes in one headless Blender run (metres, vehicle axes).
Objects are registered through the kit, as a module's build(ctx) would.

blender -b --factory-startup --python tools/tests/scenes.py -- <out_dir>
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix

OUT = sys.argv[sys.argv.index('--') + 1]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kit  # noqa: E402


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    ctx = kit.Context()
    return ctx


def mesh_object(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return bpy.data.objects.new(name, me)


def box(name, x0, x1, y0, y1, z0, z1):
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return mesh_object(name, v, f)


def wheel(name, x, y, r, width):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=width)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, 'X'))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = (x, y, r)
    return ob


def register(ctx, assembly, ob, slot, **kw):
    ctx.assembly = assembly
    ob.data.materials.append(ctx.material(slot))
    ctx.add(ob, **kw)
    return ob


def save(name):
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, name + '.blend'))


# plain: one painted box, the "vehicle" of the camera tests: 4200 x 1800, from 150 to 1300 mm up
ctx = empty_scene()
register(ctx, 'body', box('body', -0.9, 3.3, -0.9, 0.9, 0.15, 1.3), 'body', part='body shell', panel=True)
save('plain')

# car: the box on four wheels; wheelbase 2500, track 1560 front and 1580 rear, wheels 660 / 680 mm
ctx = empty_scene()
register(ctx, 'body', box('body', -0.9, 3.3, -0.9, 0.9, 0.15, 1.3), 'body', part='body shell', panel=True)
for nm, x, y, d in (('wheel_fl', 0.0, -0.78, 0.66), ('wheel_fr', 0.0, 0.78, 0.66),
                    ('wheel_rl', 2.5, -0.79, 0.68), ('wheel_rr', 2.5, 0.79, 0.68)):
    w = register(ctx, 'hardware', wheel(nm, x, y, d / 2, 0.2), 'tyre', part=nm)
    if nm.startswith('wheel_f'):
        ctx.steerable(w, 'left' if nm.endswith('l') else 'right')
save('car')


# fair: a gently curved panel, one with a 30 degree fold marked as a crease, one with the fold unmarked
def grid_panel(name, fold_deg=0.0, n=40, size=1.0, radius=3.0, x_off=0.0):
    verts, faces = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = size * i / n, size * j / n
            ang = u / radius
            x, z = radius * math.sin(ang), radius * (1 - math.cos(ang))
            if fold_deg and v > size / 2:
                t = v - size / 2
                v, z = size / 2 + t * math.cos(math.radians(fold_deg)), z + t * math.sin(math.radians(fold_deg))
            verts.append((x + x_off, v, z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + n + 1, a + n + 2, a + 1))
    ob = mesh_object(name, verts, faces)
    fold = [(i * (n + 1) + n // 2, (i + 1) * (n + 1) + n // 2) for i in range(n)]
    return ob, fold


ctx = empty_scene()
p, _ = grid_panel('panel_smooth')
register(ctx, 'body', p, 'body', panel=True)
p, fold = grid_panel('panel_creased', fold_deg=30.0, x_off=2.0)
register(ctx, 'body', p, 'body', panel=True)
ctx.crease(p, fold)
p, _ = grid_panel('panel_unmarked', fold_deg=30.0, x_off=4.0)
register(ctx, 'body', p, 'body', panel=True)
save('fair')

# seat: a bumper with a square opening, a lamp seated 2 mm proud and one sitting 6 mm proud
ctx = empty_scene()
o, i = 0.5, 0.2
verts = [(-o, -o, 0), (o, -o, 0), (o, o, 0), (-o, o, 0), (-i, -i, 0), (i, -i, 0), (i, i, 0), (-i, i, 0)]
register(ctx, 'body', mesh_object('bumper skin', verts, [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]),
         'body', part='bumper', panel=True)
for nm, dz in (('lamp_ok', 0.002), ('lamp_proud', 0.006)):
    s = 0.199
    register(ctx, 'front', mesh_object(nm + ' lens', [(-s, -s, dz), (s, -s, dz), (s, s, dz), (-s, s, dz)],
                                       [(0, 1, 2, 3)]), 'lens', part=nm)
save('seat')

# sep: closed parts; the door touches the wing, the bonnet pushes 5 mm into it, one pivot sits far away
ctx = empty_scene()
register(ctx, 'body', box('wing', 0.0, 1.0, 0.0, 0.5, 0.0, 0.5), 'body', part='wing', panel=True)
register(ctx, 'body', box('door', 1.0, 2.0, 0.0, 0.5, 0.0, 0.5), 'body', part='door', panel=True, separable=True,
         pivot=[1000.0, 0.0, 250.0])
register(ctx, 'body', box('bonnet', -0.995, 0.005, 0.05, 0.45, 0.05, 0.45), 'body', part='bonnet', panel=True,
         separable=True, pivot=[-500.0, 250.0, 250.0])
register(ctx, 'body', box('boot lid', 3.0, 3.5, 0.0, 0.5, 0.0, 0.5), 'body', part='boot lid', separable=True,
         pivot=[10000.0, 10000.0, 10000.0])
save('sep')

# rays: an outer skin, and a join where a second painted skin lies 3 mm behind it; an unpainted floor below
ctx = empty_scene()
register(ctx, 'body', mesh_object('skin_outer', [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [(0, 1, 2, 3)]),
         'body', panel=True)
register(ctx, 'body', mesh_object('skin_inner', [(0.2, -1, -0.003), (1, -1, -0.003), (1, 1, -0.003),
                                                 (0.2, 1, -0.003)], [(0, 1, 2, 3)]), 'body', panel=True)
register(ctx, 'stand', mesh_object('floor', [(-3, -3, -1), (3, -3, -1), (3, 3, -1), (-3, 3, -1)], [(0, 1, 2, 3)]),
         'floor')
save('rays')
print('SCENES DONE')
