"""Shared helpers for the tools that run inside Blender (bpy, mathutils and NumPy only).

Blender scenes are in metres with the vehicle axes of CONTRACT.md (X rear, Y right, Z up, origin on the ground
under the middle of the front axle). Every file a tool reads or writes is in millimetres.
"""
import fnmatch
import math
import os
import sys
import traceback

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import ArgParser, BadInput, EXIT_BAD, load_json  # noqa: E402,F401

GEOMETRY = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}
ZEBRA_STRIPES = 40


def argv():
    a = sys.argv
    return a[a.index('--') + 1:] if '--' in a else []


def run(main):
    """Run main(argv) inside Blender and exit with its code; bad input and crashes exit 2."""
    try:
        code = main(argv())
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else EXIT_BAD
    except BadInput as e:
        sys.stderr.write('bad input: %s\n' % e)
        code = EXIT_BAD
    except Exception:
        traceback.print_exc()
        sys.stderr.write('the tool stopped on an unexpected error\n')
        code = EXIT_BAD
    sys.stdout.flush()
    sys.stderr.flush()
    sys.exit(code)


def mm_per_unit():
    return 1000.0 * (bpy.context.scene.unit_settings.scale_length or 1.0)


def depsgraph():
    return bpy.context.evaluated_depsgraph_get()


def globs(text):
    return [g.strip() for g in (text or '').split(',') if g.strip()]


def match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def visible_geometry(include=None, exclude=None):
    """Geometry objects that render, optionally limited by name globs."""
    vl = bpy.context.view_layer
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type not in GEOMETRY or ob.hide_render or not ob.visible_get(view_layer=vl):
            continue
        if include and not match(ob.name, include):
            continue
        if exclude and match(ob.name, exclude):
            continue
        out.append(ob)
    return out


def find_objects(pattern):
    """Objects whose name equals pattern, or matches it as a glob."""
    sc = bpy.context.scene
    if pattern in sc.objects:
        return [sc.objects[pattern]]
    return [o for o in sc.objects if fnmatch.fnmatchcase(o.name, pattern)]


class MeshData:
    """World-space vertices (scene units), triangles and polygon data of one evaluated object."""

    def __init__(self, ob, dg=None, layers=False):
        dg = dg or depsgraph()
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh(preserve_all_data_layers=layers, depsgraph=dg)
        try:
            n = len(me.vertices)
            co = np.empty(n * 3, np.float64)
            me.vertices.foreach_get('co', co)
            co = co.reshape(-1, 3)
            M = np.array(ob.matrix_world, float)
            self.local = co
            self.verts = co @ M[:3, :3].T + M[:3, 3]
            me.calc_loop_triangles()
            nt = len(me.loop_triangles)
            tri = np.empty(nt * 3, np.int64)
            me.loop_triangles.foreach_get('vertices', tri)
            self.tris = tri.reshape(-1, 3)
            tp = np.empty(nt, np.int64)
            me.loop_triangles.foreach_get('polygon_index', tp)
            self.tri_poly = tp
            ne = len(me.edges)
            ev_ = np.empty(ne * 2, np.int64)
            me.edges.foreach_get('vertices', ev_)
            self.edges = ev_.reshape(-1, 2)
            np_ = len(me.polygons)
            mi = np.empty(np_, np.int64)
            me.polygons.foreach_get('material_index', mi)
            self.poly_material = mi
            nl = len(me.loops)
            le = np.empty(nl, np.int64)
            me.loops.foreach_get('edge_index', le)
            lt = np.empty(np_, np.int64)
            me.polygons.foreach_get('loop_total', lt)
            ls = np.empty(np_, np.int64)
            me.polygons.foreach_get('loop_start', ls)
            self.loop_edge, self.poly_loop_total, self.poly_loop_start = le, lt, ls
            self.edge_faces = np.bincount(le, minlength=ne) if ne else np.zeros(0, np.int64)
            self.attributes = {}
            if layers:
                for at in me.attributes:
                    if at.domain == 'EDGE' and at.data_type == 'BOOLEAN' and len(at.data) == ne:
                        v = np.zeros(ne, bool)
                        at.data.foreach_get('value', v)
                        self.attributes[at.name] = v
                self.vgroups = {}
                names = {g.index: g.name for g in ob.vertex_groups}
                if names and len(me.vertices) and hasattr(me.vertices[0], 'groups'):
                    for vi, v in enumerate(me.vertices):
                        for g in v.groups:
                            if g.group in names and g.weight >= 0.5:
                                self.vgroups.setdefault(names[g.group], set()).add(vi)
            self.materials = [s.material.name if s.material else '' for s in ev.material_slots]
        finally:
            ev.to_mesh_clear()

    def closed(self):
        return len(self.edge_faces) > 0 and bool(np.all(self.edge_faces == 2))

    def tri_normals(self):
        v = self.verts[self.tris]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        area = np.linalg.norm(n, axis=1) / 2
        return n / np.maximum(2 * area, 1e-30)[:, None], area


def bbox(objs, dg=None):
    dg = dg or depsgraph()
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for ob in objs:
        v = MeshData(ob, dg).verts
        if len(v):
            lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    if not np.all(np.isfinite(lo)):
        raise BadInput('no geometry found in the scene')
    return lo, hi


# ------------------------------------------------------------------ rendering

def add_render_args(ap, mode_default='clay'):
    ap.add_argument('--mode', choices=('lit', 'clay', 'zebra'), default=None,
                    help='lit: the scene with the finish; clay: grey; zebra: %d stripes' % ZEBRA_STRIPES)
    ap.add_argument('--finish', default=None, help='a finish name from --finishes, or "scene" (default)')
    ap.add_argument('--finishes', help='finishes JSON file (default <project>/data/finishes.json)')
    ap.add_argument('--engine', default=None, help='CYCLES (default), EEVEE or WORKBENCH')
    ap.add_argument('--device', default=None, help='CPU (default) or GPU')
    ap.add_argument('--gpu-type', default=None, help='OPTIX, CUDA, HIP, METAL or ONEAPI (default: first that works)')
    ap.add_argument('--samples', type=int, default=None)
    ap.add_argument('--hide', default='', help='comma separated name globs of objects to leave out of renders')
    ap.set_defaults(_mode_default=mode_default)


RENDER_DEFAULTS = dict(mode='clay', finish='scene', engine='CYCLES', device='CPU', gpu_type=None, samples=64)


def render_settings(a, prior=None):
    """Merge explicit arguments over a prior render.json's settings over the defaults."""
    s = dict(RENDER_DEFAULTS)
    s['mode'] = getattr(a, '_mode_default', s['mode'])
    if prior:
        for k in RENDER_DEFAULTS:
            if k in prior:
                s[k] = prior[k]
    changed = {}
    for k in RENDER_DEFAULTS:
        v = getattr(a, k, None)
        if v is not None:
            if prior and k in prior and prior[k] != v:
                changed[k] = dict(prior=prior[k], used=v)
            s[k] = v
    if s['mode'] not in ('lit', 'clay', 'zebra'):
        raise BadInput('mode must be lit, clay or zebra')
    if int(s['samples']) < 1:
        raise BadInput('samples must be at least 1')
    return s, changed


def engine_id(name):
    items = bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items.keys()
    name = (name or 'CYCLES').upper()
    want = {'CYCLES': ['CYCLES'], 'EEVEE': ['BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'],
            'WORKBENCH': ['BLENDER_WORKBENCH']}.get(name, [name])
    for w in want:
        if w in items or w == 'CYCLES':
            return w
    raise BadInput('render engine %r is not available (have: %s)' % (name, ', '.join(items)))


def setup_render(s):
    sc = bpy.context.scene
    eng = engine_id(s['engine'])
    sc.render.engine = eng
    info = dict(engine=eng)
    if eng == 'CYCLES':
        cy = sc.cycles
        dev = (s['device'] or 'CPU').upper()
        if dev == 'GPU':
            pr = bpy.context.preferences.addons['cycles'].preferences
            types = [s['gpu_type'].upper()] if s['gpu_type'] else ['OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI']
            used = None
            for t in types:
                try:
                    pr.compute_device_type = t
                    pr.get_devices()
                except (TypeError, ValueError):
                    continue
                ok = False
                for d in pr.devices:
                    d.use = d.type == t
                    ok = ok or d.use
                if ok:
                    used = t
                    break
            if not used:
                raise BadInput('no GPU device found for %s' % ', '.join(types))
            cy.device = 'GPU'
            info.update(device='GPU', gpu_type=used)
        elif dev == 'CPU':
            cy.device = 'CPU'
            info.update(device='CPU')
        else:
            raise BadInput('device must be CPU or GPU')
        cy.samples = int(s['samples'])
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = 0.02
        cy.seed = 0
        try:
            cy.use_denoising = True
            cy.denoiser = 'OPENIMAGEDENOISE'
        except (TypeError, AttributeError):
            cy.use_denoising = False
        info['samples'] = int(s['samples'])
    elif eng.startswith('BLENDER_EEVEE'):
        try:
            sc.eevee.taa_render_samples = int(s['samples'])
        except AttributeError:
            pass
        info['samples'] = int(s['samples'])
    sc.render.use_motion_blur = False
    sc.render.film_transparent = True
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '8'
    for m in list(sc.timeline_markers):           # no camera switching by markers
        sc.timeline_markers.remove(m)
    return info


def load_finishes(path):
    if not path or not os.path.isfile(path):
        return {}
    d = load_json(path, 'finishes file')
    f = d.get('finishes', d) if isinstance(d, dict) else None
    if not isinstance(f, dict):
        raise BadInput('finishes file must hold {"finishes": {name: [...]}}')
    return f


PRINCIPLED = {'base_color': 'Base Color', 'metallic': 'Metallic', 'roughness': 'Roughness',
              'coat_weight': 'Coat Weight', 'coat_roughness': 'Coat Roughness',
              'specular': 'Specular IOR Level'}


def apply_finish(name, finishes):
    """Set Principled BSDF values on the materials a finish names. Never saved back."""
    if not name or name == 'scene':
        return []
    if name not in finishes:
        raise BadInput('finish %r not found (have: %s)' % (name, ', '.join(sorted(finishes)) or 'none'))
    rules = finishes[name]
    rules = rules if isinstance(rules, list) else [rules]
    touched = []
    for r in rules:
        pats = r.get('materials', '*')
        pats = pats if isinstance(pats, list) else [pats]
        for m in bpy.data.materials:
            if not match(m.name, pats) or not m.node_tree:
                continue
            for n in m.node_tree.nodes:
                if n.type != 'BSDF_PRINCIPLED':
                    continue
                for k, inp in PRINCIPLED.items():
                    if k in r and inp in n.inputs:
                        v = r[k]
                        n.inputs[inp].default_value = (tuple(v) + (1.0,))[:4] if k == 'base_color' else float(v)
                touched.append(m.name)
    if not touched:
        raise BadInput('finish %r matches no material with a Principled BSDF' % name)
    return sorted(set(touched))


def use_nodes(idblock):
    try:
        idblock.use_nodes = True          # deprecated in newer Blender, where node trees are always on
    except AttributeError:
        pass
    return idblock.node_tree


def _override(name, color, metallic, roughness):
    m = bpy.data.materials.new(name)
    use_nodes(m)
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs['Base Color'].default_value = color
    b.inputs['Metallic'].default_value = metallic
    b.inputs['Roughness'].default_value = roughness
    return m


def _world(name):
    w = bpy.data.worlds.new(name)
    nt = use_nodes(w)
    bpy.context.scene.world = w
    if 'Background' not in nt.nodes:
        bg = nt.nodes.new('ShaderNodeBackground')
        bg.name = 'Background'
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new('ShaderNodeOutputWorld')
        nt.links.new(bg.outputs[0], out.inputs['Surface'])
    return w, nt


def apply_mode(mode, finish, finishes):
    """Prepare the scene for one review mode. Returns a description written into the JSON results."""
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    info = dict(mode=mode, finish=finish or 'scene')
    if finish and finish != 'scene' and finish not in finishes:
        raise BadInput('finish %r not found (have: %s)' % (finish, ', '.join(sorted(finishes)) or 'none'))
    if mode == 'lit':
        info['finish_materials'] = apply_finish(finish, finishes)
        return info
    for ob in sc.objects:
        if ob.type == 'LIGHT':
            ob.hide_render = True
    sc.view_settings.view_transform = 'Standard'
    if mode == 'clay':
        vl.material_override = _override('rg clay', (0.55, 0.55, 0.55, 1), 0.0, 0.45)
        w, nt = _world('rg clay world')
        bg = nt.nodes['Background']
        bg.inputs['Color'].default_value = (0.35, 0.35, 0.35, 1)
        ld = bpy.data.lights.new('rg clay sun', 'SUN')
        ld.energy = 3.0
        ld.angle = math.radians(8)
        lo = bpy.data.objects.new('rg clay sun', ld)
        sc.collection.objects.link(lo)
        d = Vector((-0.55, -0.45, 0.70)).normalized()          # light from the front left, above
        lo.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        info['rig'] = 'grey 0.55 roughness 0.45; world 0.35; sun 3 from front-left-above; scene lights off'
    else:
        vl.material_override = _override('rg zebra', (0.9, 0.9, 0.9, 1), 1.0, 0.02)
        w, nt = _world('rg zebra world')
        N = nt.nodes
        tc = N.new('ShaderNodeTexCoord')
        sep = N.new('ShaderNodeSeparateXYZ')
        asin = N.new('ShaderNodeMath')
        asin.operation = 'ARCSINE'
        scl = N.new('ShaderNodeMath')
        scl.operation = 'MULTIPLY_ADD'
        scl.inputs[1].default_value = ZEBRA_STRIPES / math.pi
        scl.inputs[2].default_value = ZEBRA_STRIPES / 2.0
        fr = N.new('ShaderNodeMath')
        fr.operation = 'FRACT'
        lt = N.new('ShaderNodeMath')
        lt.operation = 'LESS_THAN'
        lt.inputs[1].default_value = 0.5
        L = nt.links
        L.new(tc.outputs['Generated'], sep.inputs[0])
        L.new(sep.outputs['Z'], asin.inputs[0])
        L.new(asin.outputs[0], scl.inputs[0])
        L.new(scl.outputs[0], fr.inputs[0])
        L.new(fr.outputs[0], lt.inputs[0])
        L.new(lt.outputs[0], N['Background'].inputs['Color'])
        N['Background'].inputs['Strength'].default_value = 1.0
        info['rig'] = ('mirror override; world of %d white stripes evenly spaced in elevation, each %.2f degrees '
                       'of a %.2f degree period; scene lights off' % (ZEBRA_STRIPES, 90.0 / ZEBRA_STRIPES,
                                                                      180.0 / ZEBRA_STRIPES))
        info['stripes'] = ZEBRA_STRIPES
    return info


def hide_objects(patterns):
    hidden = []
    for ob in bpy.context.scene.objects:
        if patterns and match(ob.name, patterns) and not ob.hide_render:
            ob.hide_render = True
            hidden.append(ob.name)
    return hidden


def render_to(path):
    sc = bpy.context.scene
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.isfile(path):
        raise RuntimeError('render was not written: %s' % path)


def alpha_fraction(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        return float((px[3::4] > 0.5).mean()) if len(px) else 0.0
    finally:
        bpy.data.images.remove(img)


# ------------------------------------------------------------------ cameras

def camera_object(name, sensor_fit='HORIZONTAL'):
    cd = bpy.data.cameras.new(name)
    cd.sensor_fit = sensor_fit
    cd.sensor_width = 36.0
    cd.clip_start = 0.01
    cd.clip_end = 2000.0
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def camera_from_view(name, c, scale=1.0):
    """A Blender camera matching one cameras.json entry (pinhole, mm, OpenCV axes). Sets the scene resolution."""
    try:
        R = np.array(c['rotation'], float)
        C = np.array(c['position_mm'], float)
        f = float(c['focal_px'])
        cx, cy = [float(v) for v in c['centre_px']]
        w, h = int(c['width']), int(c['height'])
    except (KeyError, TypeError, ValueError) as e:
        raise BadInput('camera %r is incomplete: %s' % (name, e))
    sc = bpy.context.scene
    ob = camera_object('rg view ' + name)
    rot = np.stack([R[0], -R[1], -R[2]], 1)          # columns: Blender camera x, y (up), z (backward)
    M = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            M[i][j] = rot[i, j]
        M[i][3] = C[i] / mm_per_unit()
    ob.matrix_world = M
    cd = ob.data
    cd.lens = f * 36.0 / w
    big = max(w, h)
    cd.shift_x = ((w - 1) / 2.0 - cx) / big          # shifting the frame right moves the centre pixel left
    cd.shift_y = (cy - (h - 1) / 2.0) / big
    sc.render.resolution_x = max(1, int(round(w * scale)))
    sc.render.resolution_y = max(1, int(round(h * scale)))
    sc.render.pixel_aspect_x = sc.render.pixel_aspect_y = 1.0
    sc.camera = ob
    return ob


def look_camera(name, pos, target, up=(0, 0, 1), lens=50.0, res=(1000, 1000)):
    """A camera at pos (scene units) looking at target, image up toward `up`."""
    sc = bpy.context.scene
    ob = camera_object(name)
    ob.data.lens = lens
    fwd = (Vector(target) - Vector(pos)).normalized()
    upv = Vector(up)
    if abs(fwd.dot(upv)) > 0.999:
        upv = Vector((-1, 0, 0))
    x = fwd.cross(upv).normalized()
    y = x.cross(fwd)
    M = Matrix.Identity(4)
    for i in range(3):
        M[i][0], M[i][1], M[i][2], M[i][3] = x[i], y[i], -fwd[i], pos[i]
    ob.matrix_world = M
    sc.render.resolution_x, sc.render.resolution_y = int(res[0]), int(res[1])
    sc.camera = ob
    return ob


def pixel_ray(cam, px, py, width, height):
    """World-space origin and unit direction through pixel (px, py) of a camera, pixel centres at integers."""
    sc = bpy.context.scene
    fr = [Vector(v) for v in cam.data.view_frame(scene=sc)]
    xs, ys = [v.x for v in fr], [v.y for v in fr]
    u = (px + 0.5) / width
    v = (py + 0.5) / height
    lx = min(xs) + u * (max(xs) - min(xs))
    ly = max(ys) - v * (max(ys) - min(ys))
    M = cam.matrix_world
    if cam.data.type == 'ORTHO':
        o = M @ Vector((lx, ly, 0.0))
        d = (M.to_3x3() @ Vector((0, 0, -1))).normalized()
    else:
        o = M.translation.copy()
        d = (M.to_3x3() @ Vector((lx, ly, fr[0].z))).normalized()
    return o, d


def project_px(cam, X, width, height):
    """Pixel position (centres at integers) of a world point seen by a Blender camera, and its depth."""
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    p = world_to_camera_view(sc, cam, Vector(X))
    return np.array([p.x * width - 0.5, (1.0 - p.y) * height - 0.5]), p.z
