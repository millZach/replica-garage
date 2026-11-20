"""The kit: what every module's build(ctx) receives, and the looks and studios the render tools use. (Blender)

A module is src/<assembly>.py (or its frozen copy under accepted/) with one function:

    def build(ctx):
        body = make_my_shell(ctx)                       # your own bpy code, in scene units (metres)
        ctx.add(body, part='body shell', panel=True)    # painted skin: judged for fairness and double skins
        ctx.crease(body, sharp_edge_indices)            # real creases, left out of the fairness gate
        body.data.materials.append(ctx.material('body'))

Scene units are metres; ctx.mm(value) turns millimetres (the unit of every file) into scene units. Vehicle axes:
origin on the ground under the middle of the front axle, X toward the rear, Y toward the right, Z up.

What the kit records, so the tools can read it back from the saved scene (custom properties on each object):
  rg_assembly  the assembly that added it        rg_part      its part name (default: the object's name)
  rg_panel     painted skin                       rg_separable a part that comes off (take-apart levels 2, 3)
  rg_steer     "left" or "right" for a steerable front wheel (it turns about its own origin's vertical axis)
and a boolean edge attribute rg_crease on each mesh with creases.
"""
import json
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

PROPS = ('rg_assembly', 'rg_part', 'rg_panel', 'rg_separable', 'rg_steer')
CREASE = 'rg_crease'
PRINCIPLED = {'base_color': 'Base Color', 'metallic': 'Metallic', 'roughness': 'Roughness', 'coat': 'Coat Weight',
              'coat_roughness': 'Coat Roughness', 'transmission': 'Transmission Weight', 'ior': 'IOR',
              'emission': 'Emission Color', 'emission_strength': 'Emission Strength'}
STUDIOS = ('soft', 'gloss', 'dark-paint')


def mm_per_unit():
    return 1000.0 * (bpy.context.scene.unit_settings.scale_length or 1.0)


def read_json(path, default=None):
    if not path or not os.path.isfile(path):
        return default
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


# ------------------------------------------------------------------ looks

def principled(mat):
    try:
        mat.use_nodes = True                 # deprecated in newer Blender, where node trees are always on
    except AttributeError:
        pass
    nt = mat.node_tree
    b = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is None:
        b = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None) or nt.nodes.new(
            'ShaderNodeOutputMaterial')
        nt.links.new(b.outputs[0], out.inputs['Surface'])
    return b


def set_slot(mat, settings):
    """Write one slot's settings into a material's Principled BSDF."""
    b = principled(mat)
    for k, v in settings.items():
        inp = PRINCIPLED.get(k)
        if inp is None or inp not in b.inputs:
            continue
        if k in ('base_color', 'emission'):
            b.inputs[inp].default_value = (tuple(float(c) for c in v) + (1.0,))[:4]
            if k == 'base_color':
                mat.diffuse_color = b.inputs[inp].default_value
        else:
            b.inputs[inp].default_value = float(v)


def look_of(finishes, name=None):
    """(look name, look dict). name defaults to the proof look."""
    if not finishes:
        return None, None
    looks = finishes.get('looks', {})
    name = name or finishes.get('proof_look')
    if name not in looks:
        raise KeyError('look %r is not in finishes.json (looks: %s)' % (name, ', '.join(sorted(looks)) or 'none'))
    return name, looks[name]


def apply_look(finishes, name=None):
    """Set every slot material in the scene to a look. Returns (look name, studio preset, slots missing)."""
    name, look = look_of(finishes, name)
    if look is None:
        return None, 'soft', []
    slots = look.get('slots', {})
    missing = []
    for slot, settings in slots.items():
        m = bpy.data.materials.get(slot)
        if m is None:
            missing.append(slot)
            continue
        set_slot(m, settings)
    studio = look.get('studio', 'soft')
    if studio not in STUDIOS:
        raise KeyError('look %r has studio %r; presets are %s' % (name, studio, ', '.join(STUDIOS)))
    return name, studio, missing


# ------------------------------------------------------------------ studios

def _light(name, kind, energy, loc, target, size=1.0, size_y=None, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == 'AREA':
        ld.shape = 'RECTANGLE'
        ld.size = size
        ld.size_y = size_y or size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = (Vector(target) - Vector(loc)).normalized()
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    try:
        ob.visible_camera = False            # lights never show in the picture or its alpha
    except AttributeError:
        pass
    return ob


def _world(name, top, horizon, bottom, band_deg=10.0):
    """A world shaded by elevation: `top` above, `horizon` in a band round the horizon, `bottom` below."""
    w = bpy.data.worlds.new(name)
    try:
        w.use_nodes = True
    except AttributeError:
        pass
    nt = w.node_tree
    N, L = nt.nodes, nt.links
    bg = next((n for n in N if n.type == 'BACKGROUND'), None) or N.new('ShaderNodeBackground')
    out = next((n for n in N if n.type == 'OUTPUT_WORLD'), None) or N.new('ShaderNodeOutputWorld')
    L.new(bg.outputs[0], out.inputs['Surface'])
    tc, sep = N.new('ShaderNodeTexCoord'), N.new('ShaderNodeSeparateXYZ')
    L.new(tc.outputs['Generated'], sep.inputs[0])
    ramp = N.new('ShaderNodeValToRGB')
    s = math.sin(math.radians(band_deg))
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, tuple(bottom) + (1,)
    cr.elements[1].position, cr.elements[1].color = 1.0, tuple(top) + (1,)
    for pos, col in ((0.5 - s / 2, horizon), (0.5 + s / 2, horizon)):
        e = cr.elements.new(pos)
        e.color = tuple(col) + (1,)
    mapr = N.new('ShaderNodeMapRange')
    mapr.inputs['From Min'].default_value, mapr.inputs['From Max'].default_value = -1.0, 1.0
    L.new(sep.outputs['Z'], mapr.inputs['Value'])
    L.new(mapr.outputs['Result'], ramp.inputs['Fac'])
    L.new(ramp.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
    bpy.context.scene.world = w
    return w


def build_studio(preset, lo, hi):
    """Lights and world for a studio preset round a vehicle with bounds lo, hi (scene units). Turns scene lights
    off. Returns a description for the render log."""
    if preset not in STUDIOS:
        raise KeyError('studio %r; presets are %s' % (preset, ', '.join(STUDIOS)))
    sc = bpy.context.scene
    for ob in sc.objects:
        if ob.type == 'LIGHT':
            ob.hide_render = True
    c = (np.asarray(lo) + np.asarray(hi)) / 2
    L = float(max(hi[0] - lo[0], 1e-3))
    W = float(max(hi[1] - lo[1], 1e-3))
    H = float(max(hi[2] - lo[2], 1e-3))
    tgt = (c[0], c[1], lo[2] + H * 0.4)
    r = max(L, W) * 1.6
    if preset == 'soft':
        _world('rg studio soft', (0.55, 0.55, 0.55), (0.45, 0.45, 0.45), (0.25, 0.25, 0.25))
        _light('rg soft top', 'AREA', 900 * L * W, (c[0], c[1], hi[2] + 2.5 * H), tgt, size=L * 1.4, size_y=W * 2)
        for s in (-1, 1):
            _light('rg soft side', 'AREA', 500 * L * H, (c[0], c[1] + s * r, lo[2] + 1.5 * H), tgt, size=L * 1.5,
                   size_y=H * 2)
        desc = 'soft: grey world, one large area light above, one each side'
    elif preset == 'gloss':
        _world('rg studio gloss', (0.03, 0.03, 0.03), (0.08, 0.08, 0.08), (0.01, 0.01, 0.01))
        for i, f in enumerate((-0.3, 0.0, 0.3)):
            _light('rg gloss strip %d' % i, 'AREA', 400 * L, (c[0] + f * L, c[1], hi[2] + 1.8 * H), tgt,
                   size=L * 1.2, size_y=W * 0.06)
        for s in (-1, 1):
            _light('rg gloss card', 'AREA', 300 * L * H, (c[0], c[1] + s * r, lo[2] + 0.8 * H), tgt,
                   size=L * 1.3, size_y=H * 0.25)
        desc = 'gloss: dark world, three thin strips overhead and a card each side, hard-edged for paint to mirror'
    else:
        _world('rg studio dark-paint', (0.12, 0.12, 0.12), (0.9, 0.9, 0.9), (0.05, 0.05, 0.05), band_deg=12.0)
        for s in (-1, 1):
            _light('rg wall side', 'AREA', 700 * L * H, (c[0], c[1] + s * r, lo[2] + H), tgt, size=L * 2,
                   size_y=H * 3)
        for s in (-1, 1):
            _light('rg wall end', 'AREA', 500 * W * H, (c[0] + s * r, c[1], lo[2] + H), tgt, size=W * 2.5,
                   size_y=H * 3)
        desc = 'dark-paint: lit horizon band in the world and large lit walls on four sides'
    return desc


# ------------------------------------------------------------------ steering

def steer(angle_deg):
    """Turn every steerable wheel by angle_deg (positive: pointing toward the vehicle's right) about the vertical
    axis through its origin. Returns a function that turns them back."""
    saved = []
    a = -math.radians(angle_deg or 0.0)
    for ob in bpy.context.scene.objects:
        if ob.get('rg_steer') in ('left', 'right'):
            saved.append((ob, ob.matrix_world.copy()))
            if a:
                p = ob.matrix_world.translation.copy()
                ob.matrix_world = Matrix.Translation(p) @ Matrix.Rotation(a, 4, 'Z') @ Matrix.Translation(-p) \
                    @ ob.matrix_world
    bpy.context.view_layer.update()

    def undo():
        for ob, m in saved:
            ob.matrix_world = m
        bpy.context.view_layer.update()
    return undo


# ------------------------------------------------------------------ surfaces

class Surface:
    """Where an assembly's surface is, from every object it registered (world space, scene units)."""

    def __init__(self, assembly):
        self.assembly = assembly
        self._bvh = None
        self._names = []

    def _tree(self):
        if self._bvh is not None:
            return self._bvh
        dg = bpy.context.evaluated_depsgraph_get()
        verts, tris, owner = [], [], []
        for ob in bpy.context.scene.objects:
            if ob.get('rg_assembly') != self.assembly or ob.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META'):
                continue
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
            try:
                me.calc_loop_triangles()
                M = ob.matrix_world
                base = len(verts)
                verts += [tuple(M @ v.co) for v in me.vertices]
                for t in me.loop_triangles:
                    tris.append(tuple(base + i for i in t.vertices))
                    owner.append(ob.name)
            finally:
                ev.to_mesh_clear()
        if not tris:
            raise RuntimeError('the %s is not built yet: build it before the assemblies that sit on it'
                               % self.assembly)
        self._bvh, self._names = BVHTree.FromPolygons(verts, tris), owner
        return self._bvh

    def reset(self):
        self._bvh = None

    def hit(self, origin, direction, distance=1e6):
        """First point where a ray meets the surface: (location, normal, object name), or None."""
        loc, nor, idx, _ = self._tree().ray_cast(Vector(origin), Vector(direction).normalized(), distance)
        return None if loc is None else (loc, nor, self._names[idx])

    def nearest(self, point, distance=1e6):
        """Nearest point on the surface: (location, normal, object name), or None."""
        loc, nor, idx, _ = self._tree().find_nearest(Vector(point), distance)
        return None if loc is None else (loc, nor, self._names[idx])


# ------------------------------------------------------------------ the context

class Context:
    """Passed to each module's build(ctx) by assemble.py."""

    def __init__(self, vehicle=None, finishes=None, look=None, parts=None):
        self.vehicle = vehicle or {}
        self.dimensions = self.vehicle.get('dimensions', {})
        self.finishes = finishes
        self.look, self._look = look_of(finishes, look) if finishes else (None, None)
        self.parts = {p['part']: p for p in (parts or []) if isinstance(p, dict) and 'part' in p}
        self.assembly = None
        self.body = Surface('body')
        self.warnings = []
        self.added = {}

    # units
    def mm(self, value):
        """Millimetres to scene units. Works on a number or a sequence."""
        k = 1.0 / mm_per_unit()
        if isinstance(value, (Vector, np.ndarray)):
            return value * k
        if isinstance(value, (list, tuple)):
            return [v * k for v in value]
        return value * k

    # registration
    def add(self, obj, part=None, panel=False, separable=False, pivot=None):
        """Register obj under the calling assembly. pivot: [x, y, z] in mm (as in parts.json); the object's
        origin is moved there without moving its geometry."""
        if self.assembly is None:
            raise RuntimeError('ctx.add is only for use inside build(ctx)')
        sc = bpy.context.scene
        if obj.name not in sc.objects:
            coll = bpy.data.collections.get(self.assembly)
            if coll is None:
                coll = bpy.data.collections.new(self.assembly)
                sc.collection.children.link(coll)
            coll.objects.link(obj)
        obj['rg_assembly'] = self.assembly
        obj['rg_part'] = part or obj.name
        obj['rg_panel'] = bool(panel)
        obj['rg_separable'] = bool(separable)
        if pivot is not None:
            self.set_pivot(obj, pivot)
        self.added.setdefault(self.assembly, []).append(obj.name)
        if self.assembly == 'body':
            self.body.reset()
        return obj

    def set_pivot(self, obj, pivot_mm):
        p = Vector(self.mm(list(map(float, pivot_mm))))
        bpy.context.view_layer.update()
        cur = obj.matrix_world.translation.copy()
        delta_world = p - cur
        if obj.type == 'MESH' and obj.data is not None:
            local = obj.matrix_world.to_3x3().inverted() @ delta_world
            obj.data.transform(Matrix.Translation(-local))
            obj.data.update()
        obj.matrix_world.translation = p
        bpy.context.view_layer.update()

    def crease(self, obj, edges):
        """Mark edges of a mesh as real creases: edge indices, or (vertex, vertex) pairs."""
        me = obj.data
        at = me.attributes.get(CREASE)
        if at is None or at.domain != 'EDGE' or at.data_type != 'BOOLEAN':
            at = me.attributes.new(CREASE, 'BOOLEAN', 'EDGE')
        by_pair = None
        for e in edges:
            if isinstance(e, int):
                at.data[e].value = True
                continue
            if by_pair is None:
                by_pair = {frozenset(ed.vertices): ed.index for ed in me.edges}
            i = by_pair.get(frozenset(e))
            if i is None:
                raise ValueError('no edge between vertices %r on %s' % (tuple(e), obj.name))
            at.data[i].value = True

    def steerable(self, obj, side):
        """A front wheel that turns with the steering; its origin must sit on the steering axis."""
        if side not in ('left', 'right'):
            raise ValueError('side must be "left" or "right"')
        obj['rg_steer'] = side

    def material(self, slot):
        """The material for a slot in the current look (one material per slot; a look changes only its values)."""
        m = bpy.data.materials.get(slot)
        if m is None:
            m = bpy.data.materials.new(slot)
        if self._look is not None:
            slots = self._look.get('slots', {})
            if slot not in slots:
                raise KeyError('slot %r is not in look %r (slots: %s)' % (slot, self.look, ', '.join(sorted(slots))))
            set_slot(m, slots[slot])
        else:
            principled(m)
            if 'no finishes.json: slot materials are plain grey' not in self.warnings:
                self.warnings.append('no finishes.json: slot materials are plain grey')
        m['rg_slot'] = slot
        return m

    def part(self, name):
        """The parts.json entry for a part (its pivot is in mm, ready for ctx.add(pivot=...))."""
        if name not in self.parts:
            raise KeyError('part %r is not in data/parts.json' % name)
        return self.parts[name]
