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


for name, unmarked in (('fair', False), ('fair_bad', True)):
    ctx = empty_scene()
    p, _ = grid_panel('panel_smooth')
    register(ctx, 'body', p, 'body', panel=True)
    p, fold = grid_panel('panel_creased', fold_deg=30.0, x_off=2.0)
    register(ctx, 'body', p, 'body', panel=True)
    ctx.crease(p, fold)
    if unmarked:
        p, _ = grid_panel('panel_unmarked', fold_deg=30.0, x_off=4.0)
        register(ctx, 'body', p, 'body', panel=True)
    save(name)

# bare: geometry nobody registered through the kit
empty_scene()
bpy.context.scene.collection.objects.link(box('loose box', 0, 1, 0, 1, 0, 1))
save('bare')

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
register(ctx, 'body', box('wing', 0.0, 1.0, 0.0, 0.5, 0.0, 0.5), 'body', part='wing', panel=True,
         separable=True)
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


# hem: a removable bonnet as one object: a flat outer skin, a returned edge folded 20 mm down round its border
# and an inner face 2 mm under the skin, facing it. hem marks the return and the inner face with ctx.inner;
# hem_bad leaves them unmarked.
def bonnet(n=10, size=1.0, z=0.5):
    verts, faces = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            verts.append((size * i / n - size / 2, size * j / n - size / 2, z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + n + 1, a + n + 2, a + 1))
    outer = len(faces)
    ring = [i * (n + 1) for i in range(n + 1)] + [n * (n + 1) + j for j in range(1, n + 1)] +         [i * (n + 1) + n for i in range(n - 1, -1, -1)] + [j for j in range(n - 1, 0, -1)]
    low = []
    for k in ring:
        x, y, _ = verts[k]
        low.append(len(verts))
        verts.append((x, y, z - 0.02))
    for k in range(len(ring)):
        a, b = ring[k], ring[(k + 1) % len(ring)]
        faces.append((b, a, low[k], low[(k + 1) % len(ring)]))
    s = 0.45
    base = len(verts)
    verts += [(-s, -s, z - 0.002), (s, -s, z - 0.002), (s, s, z - 0.002), (-s, s, z - 0.002)]
    faces.append((base, base + 1, base + 2, base + 3))
    return mesh_object('bonnet', verts, faces), list(range(outer, len(faces)))


for name, mark in (('hem', True), ('hem_bad', False)):
    ctx = empty_scene()
    ob, not_skin = bonnet()
    register(ctx, 'body', ob, 'body', part='bonnet', panel=True, separable=True)
    if mark:
        ctx.inner(ob, not_skin)
    save(name)


# wave_bad: one clean tight-radius curved panel (passes), and one finely subdivided panel with a smooth
# localized S-ripple whose adjacent-face dihedral angle is under 5 deg yet wave_mm exceeds 1.0 mm.
def wave_panel(name, n=70, size=0.8, amp=0.0028, wavelength=0.12, x_off=0.0):
    verts, faces = [], []
    cx, cy = size / 2.0, size / 2.0
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = size * i / n, size * j / n
            env = math.exp(-((u - cx) ** 2 + (v - cy) ** 2) / (2 * 0.11 ** 2))
            z = amp * math.sin(2.0 * math.pi * (u - cx) / wavelength) * env
            verts.append((u + x_off, v, z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + n + 1, a + n + 2, a + 1))
    return mesh_object(name, verts, faces)


ctx = empty_scene()
p_curve, _ = grid_panel('panel_curved', n=50, size=0.6, radius=0.45, x_off=0.0)
register(ctx, 'body', p_curve, 'body', panel=True)
p_wave = wave_panel('panel_dented', x_off=1.5)
register(ctx, 'body', p_wave, 'body', panel=True)
save('wave_bad')

# cabin: exterior open-top body_shell + removable roof enclosing interior seat & dash (exterior=False)
ctx = empty_scene()
tub_v = [(x, y, z) for x in (-0.9, 3.3) for y in (-0.9, 0.9) for z in (0.15, 1.15)]
tub_f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4)]
register(ctx, 'body', mesh_object('body_shell', tub_v, tub_f), 'body', part='body_shell', panel=True, exterior=True)
register(ctx, 'body', box('roof', -0.9, 3.3, -0.9, 0.9, 1.15, 1.30), 'body', part='roof', panel=True,
         exterior=True)
register(ctx, 'interior', box('seat', 1.1, 1.6, -0.4, 0.4, 0.25, 0.85), 'seat', part='seat', exterior=False)
register(ctx, 'interior', box('dash', 0.4, 0.7, -0.6, 0.6, 0.55, 0.95), 'trim', part='dash', exterior=False)
save('cabin')

# seat_closed: bumper opening with a closed solid lamp whose front perimeter is marked with ctx.seat_edge
ctx = empty_scene()
o, i = 0.5, 0.2
verts = [(-o, -o, 0), (o, -o, 0), (o, o, 0), (-o, o, 0), (-i, -i, 0), (i, -i, 0), (i, i, 0), (-i, i, 0)]
register(ctx, 'body', mesh_object('bumper skin', verts, [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]),
         'body', part='bumper', panel=True)
lamp = box('lamp_closed', -0.199, 0.199, -0.199, 0.199, -0.04, 0.002)
register(ctx, 'front', lamp, 'lens', part='lamp_closed')
top_verts = [v.index for v in lamp.data.vertices if v.co.z > 0.0]
ctx.seat_edge(lamp, top_verts)
save('seat_closed')
print('SCENES DONE')
