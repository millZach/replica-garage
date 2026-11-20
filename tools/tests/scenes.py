"""Build the small synthetic test scenes in one headless Blender run (metres, vehicle axes).

blender -b --factory-startup --python tools/tests/scenes.py -- <out_dir>
"""
import math
import os
import sys

import bpy
import bmesh

OUT = sys.argv[sys.argv.index('--') + 1]


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    return sc


def material(name, rgb=(0.6, 0.1, 0.1)):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except AttributeError:
        pass
    for n in m.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            n.inputs['Base Color'].default_value = rgb + (1,)
    return m


def mesh_object(name, verts, faces, mat=None, origin=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if mat:
        me.materials.append(mat)
    if origin is not None:
        ox, oy, oz = origin
        me.transform(__import__('mathutils').Matrix.Translation((-ox, -oy, -oz)))
        ob.location = origin
    return ob


def box(name, x0, x1, y0, y1, z0, z1, mat=None, origin=None):
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return mesh_object(name, v, f, mat, origin)


def wheel(name, x, y, r, width, mat):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r, radius2=r, depth=width)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    ob.rotation_euler = (math.pi / 2, 0, 0)
    ob.location = (x, y, r)
    return ob


def sun():
    ld = bpy.data.lights.new('key', 'SUN')
    ld.energy = 3
    ob = bpy.data.objects.new('key', ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = (0.6, 0.2, 0.8)


def save(name):
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, name + '.blend'))


# plain: one painted box, the "vehicle" of the camera tests: 4200 x 1800, from 150 to 1300 mm up
empty_scene()
paint = material('Paint body')
box('body', -0.9, 3.3, -0.9, 0.9, 0.15, 1.3, paint)
sun()
save('plain')

# car: the box on four wheels; wheelbase 2500, track 1560 front and 1580 rear, wheels 660 / 680 mm
empty_scene()
paint, rubber = material('Paint body'), material('Rubber', (0.02, 0.02, 0.02))
box('body', -0.9, 3.3, -0.9, 0.9, 0.15, 1.3, paint)
for nm, x, y, d in (('wheel_fl', 0.0, -0.78, 0.66), ('wheel_fr', 0.0, 0.78, 0.66),
                    ('wheel_rl', 2.5, -0.79, 0.68), ('wheel_rr', 2.5, 0.79, 0.68)):
    wheel(nm, x, y, d / 2, 0.2, rubber)
sun()
save('car')


# fair: a gently curved panel and a panel with a 30 degree fold marked as a crease
def grid_panel(name, fold_deg=0.0, n=40, size=1.0, radius=3.0):
    verts, faces = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = size * i / n, size * j / n
            ang = u / radius
            x, z = radius * math.sin(ang), radius * (1 - math.cos(ang))
            if fold_deg and v > size / 2:
                t = v - size / 2
                v, dz = size / 2 + t * math.cos(math.radians(fold_deg)), t * math.sin(math.radians(fold_deg))
                z += dz
            verts.append((x, v, z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + n + 1, a + n + 2, a + 1))
    ob = mesh_object(name, verts, faces, material('Paint ' + name))
    if fold_deg:
        me = ob.data
        at = me.attributes.new('fold', 'BOOLEAN', 'EDGE')
        mid = n // 2
        for e in me.edges:
            a, b = e.vertices
            ja, jb = a % (n + 1), b % (n + 1)
            at.data[e.index].value = (ja == mid and jb == mid)
    return ob


empty_scene()
grid_panel('panel_smooth')
p = grid_panel('panel_creased', fold_deg=30.0)
p.location.x = 2.0
save('fair')

# seat: a panel with a square opening, a lamp seated 2 mm proud and one sitting 6 mm proud
empty_scene()
o, i = 0.5, 0.2
verts = [(-o, -o, 0), (o, -o, 0), (o, o, 0), (-o, o, 0), (-i, -i, 0), (i, -i, 0), (i, i, 0), (-i, i, 0)]
faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
mesh_object('panel', verts, faces, material('Paint panel'))
for nm, dz in (('lamp_ok', 0.002), ('lamp_proud', 0.006)):
    s = 0.199
    mesh_object(nm, [(-s, -s, dz), (s, -s, dz), (s, s, dz), (-s, s, dz)], [(0, 1, 2, 3)], material('Lens ' + nm))
save('seat')

# sep: closed parts; door touches the wing, the bonnet pushes 5 mm into it, one part has its pivot far away
empty_scene()
box('wing', 0.0, 1.0, 0.0, 0.5, 0.0, 0.5, material('Paint wing'))
box('door', 1.0, 2.0, 0.0, 0.5, 0.0, 0.5, material('Paint door'), origin=(1.0, 0.0, 0.25))      # hinge at front
box('bonnet', -0.995, 0.005, 0.05, 0.45, 0.05, 0.45, material('Paint bonnet'), origin=(-0.5, 0.25, 0.25))
box('far_pivot', 3.0, 3.5, 0.0, 0.5, 0.0, 0.5, material('Paint far'), origin=(10.0, 10.0, 10.0))
save('sep')

# rays: a single outer skin, and a join where a second painted skin lies 3 mm behind the first
empty_scene()
skin = material('Paint skin')
mesh_object('skin_outer', [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [(0, 1, 2, 3)], skin)
mesh_object('skin_inner', [(0.2, -1, -0.003), (1, -1, -0.003), (1, 1, -0.003), (0.2, 1, -0.003)], [(0, 1, 2, 3)],
            material('Paint skin inner'))
mesh_object('floor', [(-3, -3, -1), (3, -3, -1), (3, 3, -1), (-3, 3, -1)], [(0, 1, 2, 3)], material('Floor'))
cd = bpy.data.cameras.new('cam_top')
cd.lens = 36.0
cd.sensor_width = 36.0
cam = bpy.data.objects.new('cam_top', cd)
bpy.context.scene.collection.objects.link(cam)
cam.location = (0, 0, 3)
bpy.context.scene.camera = cam
bpy.context.scene.render.resolution_x = 200
bpy.context.scene.render.resolution_y = 100
save('rays')
print('SCENES DONE')
