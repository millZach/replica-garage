"""The kit: what every module's build(ctx) receives, and the looks and studios the render tools use. (Blender)

A module is src/<assembly>.py (frozen, once accepted, as accepted/<assembly>/NN/<assembly>.py) with one function,
build(ctx). assemble.py runs the modules in data/build.json order in a clean scene and saves the result, so a
module only makes objects: it never opens, saves or clears a scene.

    import bpy

    def build(ctx):                                     # src/body.py
        shell = make_shell(ctx)                         # your own bpy code, in scene units (metres)
        shell.data.materials.append(ctx.material('body'))
        ctx.add(shell, part='body shell', panel=True)   # painted skin: judged for fairness and double skins
        ctx.crease(shell, character_line_edges)         # real creases, left out of the fairness gate

    def build(ctx):                                     # src/front.py, manifest depends_on ["body"]
        loc, normal, _ = ctx.body.hit([-2000, -600, 650], (1, 0, 0))  # mm: where the skin is, ahead of the lamp
        lamp = make_lamp(ctx.mm(loc), normal)           # your bpy code works in scene units
        lamp.data.materials.append(ctx.material('glass'))
        ctx.add(lamp, part='headlamp_l')                # build.json seats it: {"part": "headlamp_l", "on": ...}

Units: every file and every position the kit takes or gives is in millimetres; scenes are in metres;
ctx.mm(value) converts millimetres to scene units for your own bpy code. Vehicle axes: origin on the
ground under the middle of the front axle, X toward the rear, Y toward the vehicle's right, Z up.

What the kit records, so the tools find panels, creases and parts in the saved scene without name lists
(custom properties on each object):
  rg_assembly  the assembly that added it        rg_part      its part name (default: the object's name)
  rg_panel     painted skin                       rg_separable a part that comes off (take-apart levels 2, 3)
  rg_steer     "left" or "right" for a steerable front wheel (it turns about its own origin's vertical axis)
the boolean edge attribute rg_crease (ctx.crease) and the boolean face attribute rg_inner (ctx.inner).

The render tools also use apply_look(), build_studio() and build_style() here: a look sets every slot material
from data/finishes.json; a studio preset (soft, gloss, dark-paint) lights the vehicle for evidence renders; a
presentation style (showroom, studio, daylight) dresses it for the pictures people look at.
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
INNER = 'rg_inner'
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


# ------------------------------------------------------------------ presentation styles

STYLES = ('showroom', 'studio', 'daylight')


def _style_object(name, verts, faces, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob['rg_style'] = True                    # never part of the vehicle: every tool leaves these out
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _style_material(name, **settings):
    m = bpy.data.materials.new(name)
    set_slot(m, settings)
    return m


def _disc(radius, n=64, z=0.0):
    verts = [(0.0, 0.0, z)] + [(radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n), z)
                               for i in range(n)]
    return verts, [(0, i + 1, (i + 1) % n + 1) for i in range(n)]


def _ring(r0, r1, n=96, z=0.001):
    verts, faces = [], []
    for i in range(n):
        a = 2 * math.pi * i / n
        verts += [(r0 * math.cos(a), r0 * math.sin(a), z), (r1 * math.cos(a), r1 * math.sin(a), z)]
    for i in range(n):
        j = (i + 1) % n
        faces.append((2 * i, 2 * i + 1, 2 * j + 1, 2 * j))
    return verts, faces


def _bowl(radius, wall, n=64, rings=8):
    """A floor that curves up into a wall all round: a seamless backdrop with no horizon line."""
    verts, faces = [(0.0, 0.0, 0.0)], []
    prof = [(radius * k / rings, 0.0) for k in range(1, rings + 1)]
    prof += [(radius + wall * (1 - math.cos(a)), wall * math.sin(a))
             for a in [math.pi / 2 * k / rings for k in range(1, rings + 1)]]
    prof += [(radius + wall, wall + wall * k / 2) for k in range(1, 3)]
    for r, z in prof:
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for i in range(n):
        faces.append((0, 1 + i, 1 + (i + 1) % n))
    for k in range(len(prof) - 1):
        b0, b1 = 1 + k * n, 1 + (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append((b0 + i, b1 + i, b1 + j, b0 + j))
    return verts, faces


def build_style(style, lo, hi, sky=None):
    """Light and surround the vehicle (bounds lo, hi in scene units) in a presentation style, for orbit.py and
    closeups.py --style. Separate from the evidence studios: a style adds a floor or backdrop to the picture.

    showroom  a dark room, a dark glossy floor, lit cards overhead and a lit ring on the floor round the vehicle
    studio    a pale seamless backdrop curving up from the floor, broad soft light, a soft shadow on the ground
    daylight  a sky dome from `sky`, an image file the project supplies (under refs/), on a plain ground
    Every object made is tagged rg_style and centred under the vehicle. Scene lights are turned off. Returns a
    description for the render log.
    """
    if style not in STYLES:
        raise KeyError('style %r; styles are %s' % (style, ', '.join(STYLES)))
    sc = bpy.context.scene
    for ob in sc.objects:
        if ob.type == 'LIGHT':
            ob.hide_render = True
    c = (np.asarray(lo) + np.asarray(hi)) / 2
    L, W, H = [float(max(v, 1e-3)) for v in (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])]
    half = math.hypot(L, W) / 2
    tgt = (c[0], c[1], lo[2] + 0.4 * H)
    big = half * 12

    def place(ob):
        ob.location = (c[0], c[1], 0.0)
        return ob

    if style == 'showroom':
        _world('rg style showroom', (0.004, 0.004, 0.004), (0.01, 0.01, 0.01), (0.002, 0.002, 0.002))
        place(_style_object('rg showroom floor', *_disc(big), _style_material(
            'rg showroom floor', base_color=[0.015, 0.015, 0.016], roughness=0.12, coat=1.0, coat_roughness=0.05)))
        place(_style_object('rg showroom ring', *_ring(half * 1.25, half * 1.32), _style_material(
            'rg showroom ring', base_color=[0, 0, 0], emission=[1.0, 0.97, 0.92], emission_strength=6.0)))
        for i, f in enumerate((-0.32, 0.0, 0.32)):
            _light('rg showroom card %d' % i, 'AREA', 350 * L, (c[0] + f * L, c[1], hi[2] + 1.6 * H), tgt,
                   size=W * 1.2, size_y=L * 0.12)
        for s in (-1, 1):
            _light('rg showroom side', 'AREA', 120 * L * H, (c[0], c[1] + s * half * 2.2, lo[2] + 1.2 * H), tgt,
                   size=L * 1.2, size_y=H * 0.2)
        desc = 'showroom: dark room, dark glossy floor, three lit cards overhead, a lit ring on the floor'
    elif style == 'studio':
        _world('rg style studio', (0.85, 0.85, 0.85), (0.8, 0.8, 0.8), (0.7, 0.7, 0.7))
        place(_style_object('rg studio backdrop', *_bowl(half * 4, half * 2), _style_material(
            'rg studio backdrop', base_color=[0.82, 0.82, 0.8], roughness=0.9)))
        _light('rg studio key', 'AREA', 900 * L * W, (c[0], c[1], hi[2] + 2.5 * H), tgt, size=L * 2.0,
               size_y=W * 3.0)
        _light('rg studio fill', 'AREA', 300 * L * H, (c[0] - half * 2.5, c[1] - half * 2.5, lo[2] + 1.5 * H), tgt,
               size=L * 2, size_y=H * 2)
        desc = 'studio: pale seamless backdrop, broad soft light from above and one side, soft ground shadow'
    else:
        if not sky or not os.path.isfile(sky):
            raise FileNotFoundError('the daylight style needs a sky image the project supplies (got %r)' % (sky,))
        w = bpy.data.worlds.new('rg style daylight')
        try:
            w.use_nodes = True
        except AttributeError:
            pass
        nt = w.node_tree
        bg = next((n for n in nt.nodes if n.type == 'BACKGROUND'), None) or nt.nodes.new('ShaderNodeBackground')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new('ShaderNodeOutputWorld')
        env = nt.nodes.new('ShaderNodeTexEnvironment')
        env.image = bpy.data.images.load(sky, check_existing=True)
        nt.links.new(env.outputs['Color'], bg.inputs['Color'])
        nt.links.new(bg.outputs[0], out.inputs['Surface'])
        sc.world = w
        place(_style_object('rg daylight ground', *_disc(big), _style_material(
            'rg daylight ground', base_color=[0.35, 0.35, 0.33], roughness=0.85)))
        desc = 'daylight: sky dome from %s on a plain ground' % os.path.basename(sky)
    sc.render.film_transparent = False
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

class BodySurface:
    """ctx.body: where the painted skin built so far is, for parts that must sit on it or follow it.

    The surface is the outer skin of every object registered with ctx.add(..., panel=True) so far, by the
    assemblies built before the current one and by the current one up to the call. Faces marked with ctx.inner
    (returned edges, inner faces) are not part of it. It is gathered again whenever a panel is added.

    Positions are in millimetres, vehicle coordinates, like every position the kit takes or gives. Both queries
    return (location, normal, object name): location a mathutils Vector in mm, normal a unit Vector pointing out
    of the painted side; or None when nothing is found within `distance` mm. Asking before any panel exists raises
    RuntimeError: build the body first and list it in your manifest's depends_on.
    """

    def __init__(self):
        self._bvh = None
        self._names = []

    def _tree(self):
        if self._bvh is not None:
            return self._bvh
        dg = bpy.context.evaluated_depsgraph_get()
        verts, tris, owner = [], [], []
        for ob in bpy.context.scene.objects:
            if not ob.get('rg_panel') or ob.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META'):
                continue
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh(preserve_all_data_layers=True, depsgraph=dg)
            try:
                me.calc_loop_triangles()
                at = me.attributes.get(INNER)
                inner = [False] * len(me.polygons)
                if at is not None and at.domain == 'FACE' and at.data_type == 'BOOLEAN':
                    inner = [d.value for d in at.data]
                M = ob.matrix_world
                base = len(verts)
                verts += [tuple(M @ v.co) for v in me.vertices]
                for t in me.loop_triangles:
                    if inner[t.polygon_index]:
                        continue
                    tris.append(tuple(base + i for i in t.vertices))
                    owner.append(ob.name)
            finally:
                ev.to_mesh_clear()
        if not tris:
            raise RuntimeError('ctx.body: no painted panel has been built yet; build the body first and list it '
                               'in depends_on')
        self._bvh, self._names = BVHTree.FromPolygons(verts, tris), owner
        return self._bvh

    def reset(self):
        """Drop the gathered surface so the next query gathers it again (done whenever a panel is added)."""
        self._bvh = None

    def hit(self, origin, direction, distance=1e7):
        """The first point where the ray from `origin` (mm) along `direction` meets the outer skin.

        direction need not be unit length. Returns (location in mm, normal, object name), or None if the ray
        meets nothing within `distance` mm.
        """
        k = mm_per_unit()
        loc, nor, idx, _ = self._tree().ray_cast(Vector(origin) / k, Vector(direction).normalized(), distance / k)
        return None if loc is None else (loc * k, nor, self._names[idx])

    def nearest(self, point, distance=1e7):
        """The point of the outer skin nearest to `point` (mm).

        Returns (location in mm, normal, object name), or None if nothing lies within `distance` mm.
        """
        k = mm_per_unit()
        loc, nor, idx, _ = self._tree().find_nearest(Vector(point) / k, distance / k)
        return None if loc is None else (loc * k, nor, self._names[idx])


# ------------------------------------------------------------------ the context

class Context:
    """The ctx every module's build(ctx) receives from assemble.py.

    Attributes
      ctx.vehicle     vehicle.json as a dict (maker, model, ..., "dimensions", "points"), millimetres.
      ctx.dimensions  ctx.vehicle["dimensions"], e.g. ctx.dimensions["wheelbase"].
      ctx.look        the name of the look being built (assemble.py --look, default finishes.json proof_look).
      ctx.assembly    the assembly whose build(ctx) is running.
      ctx.body        the painted skin built so far: ctx.body.hit(...) and ctx.body.nearest(...) (BodySurface).

    Methods: ctx.mm, ctx.add, ctx.crease, ctx.inner, ctx.material, ctx.steerable, ctx.part. Everything a module
    makes must pass through ctx.add, or the tools will not see it as part of the vehicle's registered parts.

    Units: every position the kit takes or gives is in millimetres, vehicle coordinates (ctx.add pivot,
    ctx.part()["pivot"], ctx.body.hit and ctx.body.nearest). The objects you build live in the scene in metres;
    ctx.mm(value) turns millimetres into scene units for your own bpy code.
    """

    def __init__(self, vehicle=None, finishes=None, look=None, parts=None):
        self.vehicle = vehicle or {}
        self.dimensions = self.vehicle.get('dimensions', {})
        self.finishes = finishes
        self.look, self._look = look_of(finishes, look) if finishes else (None, None)
        self.parts = {p['part']: p for p in (parts or []) if isinstance(p, dict) and 'part' in p}
        self.assembly = None
        self.body = BodySurface()
        self.warnings = []
        self.added = {}

    def mm(self, value):
        """Millimetres to scene units (metres in every scene the kit builds).

        Takes a number, a list or tuple (returns a list), a NumPy array or a mathutils Vector.
        Example: ctx.mm(ctx.dimensions["wheelbase"]) -> 2.5 for a 2500 mm wheelbase.
        """
        k = 1.0 / mm_per_unit()
        if isinstance(value, (Vector, np.ndarray)):
            return value * k
        if isinstance(value, (list, tuple)):
            return [v * k for v in value]
        return value * k

    def add(self, obj, part=None, panel=False, separable=False, pivot=None):
        """Register an object as part of the calling assembly, linking it into the scene if it is not yet.

        obj        a Blender object (usually a mesh) you made in build(ctx).
        part       the part's name, the one build.json seats, parts.json and the judge use (default: obj.name).
                   Several objects may share one part name, but a part that comes off (separable) must be one
                   object.
        panel      True for painted skin. Panels are judged for fairness and double skins, and become part of
                   ctx.body for the assemblies built after this one.
        separable  True for a part that comes off at take-apart level 2 or 3 (listed in data/parts.json).
        pivot      [x, y, z] in millimetres, vehicle coordinates: the hinge or hub the part turns about. The
                   object's origin is moved there without moving its geometry. Pass the one from parts.json:
                   ctx.add(door, part="door_l", separable=True, pivot=ctx.part("door_l")["pivot"]).

        Recorded on the object as custom properties rg_assembly, rg_part, rg_panel and rg_separable.
        Returns obj.
        """
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
            self._set_pivot(obj, pivot)
        self.added.setdefault(self.assembly, []).append(obj.name)
        if panel:
            self.body.reset()
        return obj

    def _set_pivot(self, obj, pivot_mm):
        if len(pivot_mm) != 3:
            raise ValueError('pivot must be [x, y, z] in mm')
        p = Vector(self.mm([float(c) for c in pivot_mm]))
        bpy.context.view_layer.update()
        delta = p - obj.matrix_world.translation
        if obj.type == 'MESH' and obj.data is not None:
            obj.data.transform(Matrix.Translation(-(obj.matrix_world.to_3x3().inverted() @ delta)))
            obj.data.update()
        obj.matrix_world.translation = p
        bpy.context.view_layer.update()

    def crease(self, obj, edges):
        """Mark edges of a mesh as real creases, so the fairness gate leaves them (and their neighbours) out.

        edges: edge indices (ints) or pairs of vertex indices (a, b) of obj's mesh. A crease is a line the real
        vehicle has: a character line, a panel's folded edge. Do not mark a kink to hide it.
        Recorded as the boolean edge attribute rg_crease, which survives modifiers that keep edge attributes.
        """
        me = obj.data
        at = me.attributes.get(CREASE)
        if at is None or at.domain != 'EDGE' or at.data_type != 'BOOLEAN':
            at = me.attributes.new(CREASE, 'BOOLEAN', 'EDGE')
        by_pair = None
        for e in edges:
            if isinstance(e, (int, np.integer)):
                at.data[int(e)].value = True
                continue
            if by_pair is None:
                by_pair = {frozenset(ed.vertices): ed.index for ed in me.edges}
            i = by_pair.get(frozenset(int(v) for v in e))
            if i is None:
                raise ValueError('no edge between vertices %r on %s' % (tuple(e), obj.name))
            at.data[i].value = True

    def inner(self, obj, faces):
        """Mark faces of a registered panel that are not its outer skin: a removable panel's returned edge (the
        hem folded under its border) and its inner face. The fairness and double-skin gates and ctx.body then
        see only the outer skin, while the part stays one object.

        faces: polygon indices of obj's mesh. Recorded as the boolean face attribute rg_inner. Model the body's
        own door shuts (jambs) as their own objects registered without panel=True, or mark them here.
        """
        me = obj.data
        at = me.attributes.get(INNER)
        if at is None or at.domain != 'FACE' or at.data_type != 'BOOLEAN':
            at = me.attributes.new(INNER, 'BOOLEAN', 'FACE')
        for f in faces:
            at.data[int(f)].value = True
        if obj.get('rg_panel'):
            self.body.reset()

    def material(self, slot):
        """The material for a slot (body, wheel, caliper, glass, trim, seat, ...) in the current look.

        There is one material per slot, named after the slot, holding the slot's settings from
        data/finishes.json for ctx.look. Assign it with obj.data.materials.append(ctx.material("body")).
        Changing look rewrites the materials' settings and changes no geometry. A slot the look does not list
        raises KeyError (add it to every look in finishes.json). With no finishes.json the material is plain grey.
        """
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

    def steerable(self, obj, side):
        """Register a front wheel (side "left" or "right") that turns with the steering.

        Renders turn it by each view's steer_deg about the vertical axis through its origin, so put the origin
        on the steering axis (the wheel's centre). Recorded as the custom property rg_steer.
        """
        if side not in ('left', 'right'):
            raise ValueError('side must be "left" or "right"')
        obj['rg_steer'] = side

    def part(self, name):
        """The data/parts.json entry for a part that comes off: {"part", "fixed_to", "pivot" (mm), "level",
        "basis"}. Raises KeyError for a part parts.json does not list."""
        if name not in self.parts:
            raise KeyError('part %r is not in data/parts.json' % name)
        return self.parts[name]
