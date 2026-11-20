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
        if ob.type not in GEOMETRY or ob.hide_render or not ob.visible_get(view_layer=vl) or ob.get('rg_style'):
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
            self.face_attributes = {}
            if layers:
                for at in me.attributes:
                    if at.domain == 'EDGE' and at.data_type == 'BOOLEAN' and len(at.data) == ne:
                        v = np.zeros(ne, bool)
                        at.data.foreach_get('value', v)
                        self.attributes[at.name] = v
                    elif at.domain == 'FACE' and at.data_type == 'BOOLEAN' and len(at.data) == np_:
                        v = np.zeros(np_, bool)
                        at.data.foreach_get('value', v)
                        self.face_attributes[at.name] = v
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

    def inner(self):
        """Boolean per polygon: marked with ctx.inner (returned edge or inner face, not outer skin)."""
        return self.face_attributes.get('rg_inner', np.zeros(len(self.poly_loop_total), bool))

    def outer_tris(self):
        """The triangles of the outer skin: every triangle whose polygon is not marked inner."""
        return self.tris[~self.inner()[self.tri_poly]] if len(self.tris) else self.tris

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

def project_dir(a):
    """--project, or the folder above this tools/ folder."""
    if getattr(a, 'project', None):
        return os.path.abspath(a.project)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_project_arg(ap):
    ap.add_argument('--project', default=None, help='the project folder (default: the folder above tools/)')


def add_render_args(ap):
    ap.add_argument('--mode', choices=('lit', 'clay', 'zebra'), default=None,
                    help='lit: the look under its studio; clay: grey; zebra: %d stripes' % ZEBRA_STRIPES)
    ap.add_argument('--look', default=None, help='a look in data/finishes.json (default: the proof look)')
    ap.add_argument('--device', default=None, help='CPU (default) or GPU')
    ap.add_argument('--gpu-type', default=None, help='OPTIX, CUDA, HIP, METAL or ONEAPI (default: first that works)')
    ap.add_argument('--samples', type=int, default=None)
    ap.add_argument('--hide', default='', help='parts or objects, by name or glob, left out of the pictures')


RENDER_DEFAULTS = dict(samples=128, device='CPU', gpu_type=None, adaptive_threshold=0.02, denoise=True)
TRIAL_SAMPLES = 16


def render_settings(a, settings_path, trial=False):
    """Sampling and device for a render. Evidence renders read them from settings_path (data/render.json) when it
    exists, so every round matches; otherwise they come from the arguments and are written there after the first
    render. Trial renders neither read nor write it. Returns (settings, ignored arguments, path to write or None)."""
    s = dict(RENDER_DEFAULTS)
    if trial:
        s['samples'] = TRIAL_SAMPLES
    stored = None
    if not trial and settings_path and os.path.isfile(settings_path):
        stored = load_json(settings_path, 'render settings')
        if not isinstance(stored, dict):
            raise BadInput('%s must hold a JSON object' % settings_path)
    ignored = {}
    if stored:
        for k in RENDER_DEFAULTS:
            if k in stored:
                s[k] = stored[k]
        for k in ('samples', 'device', 'gpu_type'):
            v = getattr(a, k, None)
            if v is not None and v != stored.get(k):
                ignored[k] = v
    else:
        for k in ('samples', 'device', 'gpu_type'):
            v = getattr(a, k, None)
            if v is not None:
                s[k] = v
    if int(s['samples']) < 1:
        raise BadInput('samples must be at least 1')
    if str(s['device']).upper() not in ('CPU', 'GPU'):
        raise BadInput('device must be CPU or GPU')
    for k, v in ignored.items():
        print('NOTE %s=%s ignored: %s holds the settings every round uses' % (k, v, settings_path))
    return s, ignored, (None if trial or stored else settings_path)


def write_settings(path, s, info):
    if path:
        from _common import save_json
        save_json(path, dict(s, engine='CYCLES', gpu_type=info.get('gpu_type', s.get('gpu_type')),
                             written_by='first evidence render', blender=bpy.app.version_string))


def setup_render(s):
    """Cycles with the given sampling and device; transparent film so the alpha is the silhouette."""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    cy = sc.cycles
    info = dict(engine='CYCLES')
    dev = str(s['device'] or 'CPU').upper()
    if dev == 'GPU':
        pr = bpy.context.preferences.addons['cycles'].preferences
        types = [s['gpu_type'].upper()] if s.get('gpu_type') else ['OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI']
        used = None
        for t in types:
            try:
                pr.compute_device_type = t
                pr.get_devices()
            except (TypeError, ValueError):
                continue
            found = False
            for d in pr.devices:
                d.use = d.type == t
                found = found or d.use
            if found:
                used = t
                break
        if used:
            cy.device = 'GPU'
            names = [d.name for d in pr.devices if d.use]
            info.update(device='GPU', gpu_type=used, devices=names)
        else:
            cy.device = 'CPU'
            info.update(device='CPU', gpu_type=None, devices=['processor'],
                        fallback='no %s device found; rendering on the processor' % ' or '.join(types))
            print('DEVICE FALLBACK: a graphics card was asked for, but no %s device was found; '
                  'rendering on the processor' % ' or '.join(types), flush=True)
    else:
        cy.device = 'CPU'
        info.update(device='CPU', gpu_type=None, devices=['processor'])
    print('DEVICE %s %s' % (info['device'], ', '.join(([info['gpu_type']] if info.get('gpu_type') else []) +
                                                       info['devices'])), flush=True)
    cy.samples = int(s['samples'])
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = float(s.get('adaptive_threshold', 0.02))
    cy.seed = 0
    cy.use_denoising = bool(s.get('denoise', True))
    if cy.use_denoising:
        try:
            cy.denoiser = 'OPENIMAGEDENOISE'
        except TypeError:
            cy.use_denoising = False
    info.update(samples=int(s['samples']), denoise=cy.use_denoising)
    sc.render.use_motion_blur = False
    sc.render.film_transparent = True
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '8'
    for m in list(sc.timeline_markers):           # no camera switching by markers
        sc.timeline_markers.remove(m)
    return info


def load_finishes(project):
    import kit
    import _formats as F
    f = kit.read_json(os.path.join(project, 'data', 'finishes.json'))
    return None if f is None else F.finishes(f)


def use_nodes(idblock):
    try:
        idblock.use_nodes = True          # deprecated in newer Blender, where node trees are always on
    except AttributeError:
        pass
    return idblock.node_tree


def _override(name, color, metallic, roughness):
    import kit
    m = bpy.data.materials.new(name)
    b = kit.principled(m)
    b.inputs['Base Color'].default_value = color
    b.inputs['Metallic'].default_value = metallic
    b.inputs['Roughness'].default_value = roughness
    return m


def _world(name):
    w = bpy.data.worlds.new(name)
    nt = use_nodes(w)
    bpy.context.scene.world = w
    if not any(n.type == 'BACKGROUND' for n in nt.nodes):
        bg = nt.nodes.new('ShaderNodeBackground')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new('ShaderNodeOutputWorld')
        nt.links.new(bg.outputs[0], out.inputs['Surface'])
    return w, nt, next(n for n in nt.nodes if n.type == 'BACKGROUND')


def apply_mode(mode, look, finishes, lo, hi):
    """Prepare the scene for one review mode. Returns a description written into the JSON results."""
    import kit
    sc = bpy.context.scene
    vl = bpy.context.view_layer
    if look and not finishes:
        raise BadInput('look %r asked for, but there is no data/finishes.json' % look)
    try:
        name, studio, missing = kit.apply_look(finishes, look) if finishes else (None, 'soft', [])
    except KeyError as e:
        raise BadInput(str(e).strip('"'))
    info = dict(mode=mode, look=name)
    if mode == 'lit':
        info.update(studio=studio, rig=kit.build_studio(studio, lo, hi), slots_not_in_scene=missing)
        return info
    for ob in sc.objects:
        if ob.type == 'LIGHT':
            ob.hide_render = True
    sc.view_settings.view_transform = 'Standard'
    if mode == 'clay':
        vl.material_override = _override('rg clay', (0.55, 0.55, 0.55, 1), 0.0, 0.45)
        w, nt, bg = _world('rg clay world')
        bg.inputs['Color'].default_value = (0.35, 0.35, 0.35, 1)
        ld = bpy.data.lights.new('rg clay sun', 'SUN')
        ld.energy = 3.0
        ld.angle = math.radians(8)
        sun = bpy.data.objects.new('rg clay sun', ld)
        sc.collection.objects.link(sun)
        d = Vector((-0.55, -0.45, 0.70)).normalized()          # light from the front left, above
        sun.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
        info['rig'] = 'grey 0.55 roughness 0.45; world 0.35; sun 3 from front-left-above; scene lights off'
    else:
        vl.material_override = _override('rg zebra', (0.9, 0.9, 0.9, 1), 1.0, 0.02)
        w, nt, bg = _world('rg zebra world')
        N, L = nt.nodes, nt.links
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
        L.new(tc.outputs['Generated'], sep.inputs[0])
        L.new(sep.outputs['Z'], asin.inputs[0])
        L.new(asin.outputs[0], scl.inputs[0])
        L.new(scl.outputs[0], fr.inputs[0])
        L.new(fr.outputs[0], lt.inputs[0])
        L.new(lt.outputs[0], bg.inputs['Color'])
        bg.inputs['Strength'].default_value = 1.0
        info['rig'] = ('mirror override; a world of %d white stripes evenly spaced in elevation, %.2f degrees each '
                       'in a %.2f degree period; scene lights off' % (ZEBRA_STRIPES, 90.0 / ZEBRA_STRIPES,
                                                                       180.0 / ZEBRA_STRIPES))
        info['stripes'] = ZEBRA_STRIPES
    return info


def add_style_args(ap):
    ap.add_argument('--style', default=None, help='showroom, studio or daylight (default: "style" in finishes.json)')
    ap.add_argument('--sky', default=None, help='sky image for daylight (default: "sky" in finishes.json)')


def resolve_style(a, finishes, project, default=None):
    """The presentation style to use: --style, else finishes.json "style", else `default` (None: no style).
    Returns (style, sky path or None); bad input when daylight has no readable sky file."""
    import kit
    style = a.style or (finishes or {}).get('style') or default
    if style is None:
        return None, None
    if style not in kit.STYLES:
        raise BadInput('style %r; styles are %s' % (style, ', '.join(kit.STYLES)))
    sky = None
    if style == 'daylight':
        sky = a.sky or (finishes or {}).get('sky')
        if not sky:
            raise BadInput('the daylight style needs a sky image: give --sky or "sky" in data/finishes.json')
        sky = sky if os.path.isabs(sky) else os.path.join(project, sky)
        if not os.path.isfile(sky):
            raise BadInput('sky image not found: %s' % sky)
    return style, sky


def apply_style(style, sky, look, finishes, lo, hi):
    """The look's slot materials, then a presentation style round the vehicle (kit.build_style)."""
    import kit
    if look and not finishes:
        raise BadInput('look %r asked for, but there is no data/finishes.json' % look)
    try:
        name, _, missing = kit.apply_look(finishes, look) if finishes else (None, None, [])
    except KeyError as e:
        raise BadInput(str(e).strip('"'))
    return dict(mode='lit', look=name, style=style, rig=kit.build_style(style, lo, hi, sky),
                slots_not_in_scene=missing)


def hide_objects(patterns):
    """Hide the objects registered under matching part names (globs allowed). Returns their names; a pattern
    that matches no registered part is bad input."""
    hidden = []
    for pat in patterns or []:
        if not any(ob.get('rg_part') is not None and match(str(ob['rg_part']), [pat])
                   for ob in bpy.context.scene.objects):
            raise BadInput('no registered part matches %r' % pat)
    for ob in bpy.context.scene.objects:
        if patterns and ob.get('rg_part') is not None and match(str(ob['rg_part']), patterns) \
                and not ob.hide_render:
            ob.hide_render = True
            ob.hide_viewport = True           # also out of the way of every ray the tools cast
            hidden.append(ob.name)
    if hidden:
        bpy.context.view_layer.update()
    return hidden


def registered(prop, value=True):
    """Objects the kit registered with a property, e.g. registered('rg_panel')."""
    return [o for o in visible_geometry() if o.get(prop) == value]


def part_objects(name):
    """Geometry objects the kit registered under a part name (ctx.add(obj, part=name))."""
    return [o for o in bpy.context.scene.objects if o.type in GEOMETRY and o.get('rg_part') == name]


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
    """A Blender camera matching one cameras.json entry (mm, OpenCV axes; perspective or orthographic).
    Sets the scene resolution to the view's picture size times scale."""
    try:
        R = np.array(c['rotation'], float)
        C = np.array(c['position_mm'], float)
        cx, cy = [float(v) for v in c['centre_px']]
        w, h = int(c['width']), int(c['height'])
        ortho = c.get('kind', 'perspective') == 'orthographic'
        f = float(c['scale_px_per_mm'] if ortho else c['focal_px'])
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
    if ortho:
        cd.type = 'ORTHO'
        cd.ortho_scale = max(w, h) / f / mm_per_unit()
        cd.sensor_fit = 'AUTO'
    else:
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
