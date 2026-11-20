# Tool contract

What each bundled tool takes and gives back, the files they share, and the gate limits.

## Ground rules

- Python 3.10 or newer. Plain tools need only NumPy, SciPy and Pillow (OpenCV is used when present).
- Tools marked **Blender** run inside Blender in background mode:
  `blender -b [file.blend] --python tools/<tool>.py -- <arguments>`.
- Every tool prints one line of usage when run with no arguments, writes its results as JSON beside any
  pictures, and exits 0 on success, 1 when a gate it measures fails, 2 on bad input. This holds for tools
  whose every input has a default too: run them with at least `--project <folder>`.
- Bad input names the file, the entry and the missing or wrong key, for example
  `landmarks.json view 'side': missing key 'steer_deg'`. A crash also exits 2, never 1.
- Every tool finds the project as the folder above its `tools/` folder, or takes `--project <folder>`. Files
  default to their places in the layout below.
- Units: millimetres in every file; Blender scenes are in metres.
- Vehicle coordinates: origin on the ground under the middle of the front axle; X toward the rear, Y toward
  the vehicle's right, Z up.
- Pixels: origin at the top left, whole numbers at pixel centres.
- Evidence renders use Cycles, because paint is judged by what it mirrors. The device (`--device CPU|GPU`,
  `--gpu-type OPTIX|CUDA|HIP|METAL|ONEAPI`) is an argument; nothing assumes one maker's card.

## Project layout

The manager copies this `tools/` folder into the project at Step 1, so every sub-agent finds it there.

```
<project>/
  tools/               a copy of this folder
  refs/photos/         reference photos, never edited
  refs/blueprints/     drawings, if any were found
  refs/masks/          one silhouette mask per measured view (from mask_photo.py)
  refs/sources.json    one entry per reference file
  data/vehicle.json    the exact variant, the maker's dimensions, named points
  data/landmarks.json  where known points appear in each photo or drawing
  data/cameras.json    solved cameras, each graded precise or visual
  data/choices.md      everything the user chose or accepted, in their words
  data/finishes.json   named looks and the material of each slot in each look
  data/plan.md         assemblies, who builds each, the order
  data/build.json      assemblies in build order, with the accepted version of each
  data/build-workshop.json  take-apart level 3: the build list of the workshop copy, same format
  data/parts.json      take-apart levels 2 and 3: every part that comes off
  data/limits.json     gate limits for this project (starts as a copy of tools/default_limits.json)
  data/render.json     render settings, written by the first evidence render and reused by every later one
  data/log.md          when each sub-agent started and stopped, and its usage where the agent tool reports it
  src/<assembly>.py    a builder's working module, with build(ctx)
  accepted/<assembly>/NN/   frozen copy of an accepted module: <assembly>.py and manifest.json
  notes/<assembly>/    brief-00.md, then note-NN.md (manager) answered by pass-NN.md (builder)
  out/vehicle.blend    the assembled vehicle, built by assemble.py
  out/workshop.blend   take-apart level 3: the workshop copy, built by assemble.py --build data/build-workshop.json
  out/work-<assembly>.blend  a builder's own trial assembly
  evidence/round-NN/   one frozen candidate: vehicle.blend, build.json, lit/ clay/ zebra/ closeups/ boards/,
                       the tools' JSON, gates.json, judge.md, marks.json, user-marks.md; at level 3 also
                       workshop.blend, build-workshop.json and exploded/
```

## File formats

Only the keys the tools read are fixed. Add others freely. A key is required unless marked optional.

- **`vehicle.json`**: `maker`, `model`, `generation`, `years`, `trim`; `dimensions` with `length`, `width`
  (body, without mirrors), `height`, `wheelbase`, `track_front`, `track_rear`, `overhang_front`,
  `tyre_diameter_front|rear`, `tyre_width_front|rear`, `rim_diameter_front|rear`; `estimated` (optional): a
  list of the dimensions above that were scaled off a drawing because the maker gave no figure; `points`
  (optional): any further named point with its `[x, y, z]`. The named points below are worked out from the
  dimensions. A dimension nobody can supply is left out, and the points that need it are then not available: a
  view that marks one is refused, naming the point. Estimated dimensions may be used to solve cameras and are
  left out of the dimension gate. `rim_diameter_*` is the rim's visible outer edge, where metal meets tyre,
  which is wider than the nominal wheel size; if only the nominal size is known, leave it out.
- **`landmarks.json`**: a list of `{ "view": name, "file": path, "crop": [u0, v0, u1, v1] (optional),
  "kind": "photo" | "drawing", "steer_deg": number, "focal_mm": number and "sensor_mm": number (optional, when
  the photo's data gives them; both or neither), "points": { point name: [u, v] } }`. Pixels are measured
  from the top left of the whole file. Several views may share one file, each with its own `crop`: a blueprint
  sheet with four views is four entries. `steer_deg` is positive when the front wheels point toward the
  vehicle's right. A view's **picture** is its file cut to its crop. landmarks.json is the only file that says
  which file and crop a view is: `mask_photo.py`, `compare.py`, `rays.py` and `solve_cameras.py --triangulate`
  read them from here.
- **Pixels file** (for `rays.py --pixels` and `solve_cameras.py --triangulate`): a list of
  `{ "name": text, "view": name, "u": number, "v": number }`, in pixels of the whole file.

### Named points

Suffixes: `fl`, `fr`, `rl`, `rr` for front left, front right, rear left, rear right. Left is the vehicle's own
left, at negative Y.

| Point | Where it is |
|---|---|
| `contact_*` | Middle of the tyre's contact patch: on the ground, on the axle line, at half the track from the centreline |
| `hub_*` | Centre of the wheel as you see it from outside: on the axle line, at axle height (half the tyre diameter), on the tyre's outer face (half the track plus half the tyre width from the centreline) |
| `rim_top_*`, `rim_bottom_*`, `rim_front_*`, `rim_rear_*` | The four ends of the rim's edge, half a rim diameter from `hub_*`, in the same plane. Use these only on wheels that are pointing straight ahead |
| `front_extreme`, `rear_extreme` | The foremost and rearmost point of the body. Only X is known (from the front overhang and the length) |
| `roof_top` | The highest point of the body. Only Z is known (the height) |
| `side_extreme_l`, `side_extreme_r` | The widest point of the body on each side. Only Y is known (half the width) |

For the last three rows the solver finds the unknown coordinates along with the camera, so click the point
where the silhouette reaches furthest. A point with unknown coordinates is the same point in every view that
marks it. A view's `steer_deg` turns the front `hub_*` and `rim_*` points about the wheel's vertical axis. A
view needs at least six points spread across the picture; the tool refuses fewer.

A photo is only as good as the depth its points cover. When every fully known point lies in one plane, as in
a face-on side photo showing two wheels, the direction solves and the distance does not. The solver checks
this and grades such a view `visual`, unless its focal length is given or it is a drawing. "In one plane"
means the points' thinnest spread is under a tenth of their widest. Three-quarter photos, which see wheels on
both sides, are the ones that solve well.
- **`cameras.json`**: `{ "cameras": { view: camera } }`. Per camera: `kind` (`perspective` or
  `orthographic`); `position_mm` `[x, y, z]`; `rotation`, a 3 by 3 list whose rows are the camera's axes in
  vehicle coordinates (x right, y down, z forward, so a point maps to `rotation · (X − position)`);
  `focal_px` for a perspective camera or `scale_px_per_mm` for an orthographic one; `centre_px` `[u, v]`, the
  optical centre; `width` and `height`, the size of the view's picture; `steer_deg`; `rms_mm`; `rms_px`;
  `grade` (`precise` or `visual`). The solver also writes `planar`, `notes` and each point's error; the tools
  do not need them. An orthographic camera's position is a point on its axis, 20 m in front of the vehicle.
- **`sources.json`**: per file: `file`, `url`, `licence`, `views` (a list: a blueprint sheet holds several),
  `variant_ok` (true or false), `shows`.
- **`finishes.json`**: `proof_look`: the look every round is judged under; `looks`:
  `{ look name: { "studio": preset, "slots": { slot: settings } } }`. Slots are free names such as `body`,
  `wheel`, `caliper`, `glass`, `trim`, `seat`. Settings (each optional): `base_color` `[r, g, b]`, `metallic`,
  `roughness`, `coat`, `coat_roughness`, `transmission`, `ior`, `emission` `[r, g, b]`, `emission_strength`.
  Studio presets, built by the kit: `soft` (large soft lights, for matt and pale finishes), `gloss`
  (hard-edged cards and strips for paint to mirror), `dark-paint` (large lit walls and a lit horizon so a dark
  body shows its outline). Each slot is one material in the scene, named after the slot, so a look changes
  only the materials' settings. Without finishes.json, slot materials are plain grey and lit renders use `soft`.
- **`build.json`**: a list of `{ "assembly": name, "version": NN, "seats": [ { "part": name, "on": panel } ] }`
  in build order. `seats` lists only the parts that sit against a body panel (a lamp in its opening, a mirror
  on a door) with the panel each sits on, using the names the builders registered; it is `[]` when there are
  none. Wheels and other parts that touch no panel are not listed.
- **`manifest.json`**: `assembly`, `version`, `sha256` of the module file, `depends_on`: the assemblies whose
  surface the module asks for (usually `["body"]`). The assembly and version must match the folder it is in.
- **`parts.json`**: a list of `{ "part": name, "fixed_to": name, "pivot": [x, y, z], "level": 2 | 3,
  "basis": "measured" | "reconstructed", "assembly": name (optional) }`. `fixed_to` is another part in the
  list, or `shell` for the body that never comes off. `assembly` is the assembly that builds the part; with it,
  a part missing from a scene whose build did not include that assembly is reported as not built instead of
  failing. The pivot here is the one that counts; builders pass it to `ctx.add`.
- **`marks.json`**: a list of `{ "n": number, "picture": path, "shape": "box" | "ellipse" | "outline",
  "points": [[u, v], ...] }`. A box or ellipse takes two corner points, an outline two or more (optional
  `closed`, default true). `picture` is read relative to the folder marks.json is in.
- **`limits.json`**: one number per gate, with the names used in `default_limits.json`. Leave a gate out to
  keep its default.

## The kit

`tools/kit.py` is what every module's `build(ctx)` receives. Its docstrings are the reference. In short:

- `ctx.vehicle`, `ctx.mm(value)`: the dimensions, and millimetres to scene units.
- Every position the kit takes or gives is in **millimetres, vehicle coordinates**: `ctx.add(pivot=...)`,
  `ctx.part(...)["pivot"]`, `ctx.body.hit` and `ctx.body.nearest`. The objects a module builds live in the
  scene in metres; `ctx.mm` converts for the module's own code.
- `ctx.add(obj, part=..., panel=False, separable=False, pivot=None)`: registers an object under the calling
  assembly. `panel=True` marks painted skin for the fairness and double-skin gates. `part` defaults to the
  object's name. A part that comes off is one object. `pivot` moves the object's origin there without moving
  its geometry.
- `ctx.crease(obj, edges)`: marks edges that are real creases, so the fairness gate leaves them out.
- `ctx.inner(obj, faces)`: marks faces of a panel that are not its outer skin, so the fairness and double-skin
  gates and `ctx.body` see only the outer skin. A removable panel (bonnet, door skin) is one object registered
  with `panel=True, separable=True`; its returned edge (the hem folded under its border) and its inner face are
  marked with `ctx.inner`. The body's own door shuts (jambs) are not panels: build them as their own objects
  without `panel=True`, or mark them with `ctx.inner`.
- `ctx.material(slot)`: the material for a slot in the current look. Changing look changes no geometry. A slot
  the look does not list is an error in the module.
- `ctx.body.hit(origin, direction)` and `ctx.body.nearest(point)`: where the painted skin is, for parts that
  must sit on it: the outer skin of every object registered with `panel=True` so far. Each returns
  `(location, normal, object name)` or nothing. Available to every assembly built after the body.
- `ctx.steerable(obj, side)`: registers a front wheel so a view can be rendered at its photo's steering angle.
  The wheel turns about the vertical axis through its origin.
- `ctx.part(name)`: the part's entry in `parts.json`, so a builder can pass its pivot to `ctx.add`.

The kit records what it is told on each object, and the tools read nothing else to find panels, creases and
parts: custom properties `rg_assembly`, `rg_part`, `rg_panel`, `rg_separable`, `rg_steer`; the boolean edge
attribute `rg_crease`; the boolean face attribute `rg_inner`.

## The tools

| Tool | Runs in | Input | Output |
|---|---|---|---|
| `solve_cameras.py` | Python | `vehicle.json`, `landmarks.json` | `cameras.json`. A photo solves to a perspective camera: position, rotation, focal length (held at `focal_mm` / `sensor_mm` times the file's width when given) and the optical centre at the middle of the file (`--free-centre` solves it too). A drawing solves to an orthographic one: scaled and placed from its landmarks. Each view, photo or drawing, is graded `precise` when its error at the known points is inside the camera limit, otherwise `visual`. Exit 1 when fewer than `--min-precise` views (default `min_precise_views` from the limits, 3) are precise. With `--triangulate <pixels file>` it instead takes one feature seen in two or more solved views and prints its position on the vehicle and how far off it lands in each view, also written beside the pixels file as `<name>-triangulated.json`. |
| `mask_photo.py` | Python | one view from `landmarks.json`; optional `--seed <render of the same view>` | `refs/masks/<view>.png` and a preview with the mask's edge drawn on the picture, to be checked by eye. A photo on a plain background works alone. A drawing works alone too: the mask is everything inside its outermost line, within the view's crop. A photo on a busy background needs `--seed`: a render of the model through that view's camera, which tells it roughly where the vehicle is. Exit 1 when the mask touches the picture's edge, covers under 1% or over 95% of it, or (a photo without a seed) the background is not plain. |
| `assemble.py` | Blender | `--build <file>` (default `data/build.json`); optional `--working <assembly>`; `--look <name>`; `--out` | Checks every accepted module against its manifest hash, runs each `build(ctx)` in order in a clean scene and saves the result to `--out`: by default `out/vehicle.blend`, `out/workshop.blend` for `--build data/build-workshop.json`, `out/work-<assembly>.blend` with `--working`. `--working <assembly>` takes that one module from `src/` in place of its accepted version, or after the listed ones if it is not in the list yet. Exit 1 on a hash mismatch, an assembly in `depends_on` that is not built earlier in the list, or any module error; nothing is saved then. |
| `render_views.py` | Blender | scene, `cameras.json`, `--mode lit\|clay\|zebra`, `--look`, `--out`; optional `--view <name>` and `--trial` | One render per camera, or only the named view, at its picture's own size and steering angle, orthographic cameras included: `<out>/<view>.png` with a transparent background, so its alpha is the silhouette. *Lit* is the look under its studio preset; *clay* is plain grey, to show shape without paint; *zebra* mirrors 40 stripes in the paint, to show ripples: 40 white bands evenly spaced in elevation, each half of its 4.5 degree period. An evidence run writes its sampling and device to `data/render.json` the first time and reads them from it afterwards, so every round matches: once the file exists, `--samples` and `--device` are ignored and the output says so. `--trial` is for builders: half size, few samples, and it neither reads nor writes `render.json`. Exit 1 when a view's camera in Blender lands more than 0.5 px from the cameras.json model, or a view shows no vehicle. |
| `compare.py` | Python | pictures, masks, renders, `cameras.json` | `boards/<view>.jpg` (picture beside render, same scale) and `outline.json`: median and 95th-percentile distance between the two silhouettes per view, scaled to a 1600 px wide image. Only precise views count toward the gate; a precise view with no mask counts as failed. |
| `dimensions.py` | Blender | scene, `vehicle.json` | `dimensions.json`: each dimension with its error in mm. Width leaves out parts whose name contains "mirror". Estimated dimensions and dimensions the maker gives no figure for are reported and not judged. |
| `closeups.py` | Blender | scene, `--size-mm` (default 600), `--mode`, `--look`, `--out`; optional `--hide <part>,<part>,...` | The **close-up ring**: close views covering both sides, front, rear and roof, named by position, with `closeups.json`. The tool checks that both sides are covered: exit 1 when any region's coverage of the surface seen from outside is under 95%. It runs on whatever scene it is given (`vehicle.blend`, `workshop.blend`); `--hide` takes several parts at once, so nested parts can be uncovered. |
| `fairness.py` | Blender | scene | `fairness.json`: for each panel, the angle between neighbouring faces at the 99th percentile and the maximum, leaving out marked creases (and edges within 10 mm of them) and faces marked inner. |
| `rays.py` | Blender | scene, `cameras.json`; `--grid N` (default 64: a 64 by 64 grid through each camera) or `--pixels <pixels file>` | `rays.json`: for each ray, every surface it passes through in order: object, material, position. With `--grid` the list is a compact table per view (object and material names once, then one row per ray), and it also lists every place where one painted panel lies within `--stack-mm` (default 10) behind another: a double skin. Each panel is traced on its own for this, so coincident skins are found. `--pixels` traces object by object for a full listing. |
| `seating.py` | Blender | scene, and either `build.json` or `--part <name> --on <panel>` | `seating.json`: for each listed part, the signed step in mm between part and panel at points all round the part's edge (+ proud, − sunk). A builder uses the `--part` form on its own trial assembly. A seat in build.json whose part or panel is not in the scene fails. |
| `separation.py` | Blender | scene, `parts.json`, `--level 2\|3` | `separation.json`: each listed part is its own object with its pivot, and no two overlap by more than `--tolerance-mm` (default 0.5). Also renders an exploded view, `<out>/exploded.png`. `--level 2` checks only the parts with `"level": 2`; `--level 3` checks all. |
| `annotate.py` | Python | a picture and `marks.json` | The marked picture, each mark numbered (default `<name>-marked.<ext>` beside the picture). Exit 1 when a mark lies outside the picture: its pixels belong to another picture. |
| `gates.py` | Python | one `evidence/round-NN/` folder, `limits.json` | `gates.json` in that folder: every gate with its value, its limit and pass or fail, the overall result, and which limits differ from the defaults. A needed gate with no evidence in the round fails unless skipped with `--skip`; separation is needed only when `data/parts.json` exists. |
| `wait_for.py` | Python | a file path and a timeout | Exit 0 when the file exists and has stopped changing, 1 on timeout. |

### What "own object with its pivot" means

A listed part passes `separation.py` when exactly one object in the scene is registered under its part name,
with `separable=True`, its mesh shared with no other object, and that object's origin is within 1 mm of the
pivot in `parts.json`. A part with no object is **not built**, listed and not failing, when parts.json names
its `assembly` and that assembly is not among those the scene was built from; otherwise it is **missing** and
fails. The exploded view moves each part away from the part it is fixed to, or from the vehicle's centre for
`shell`.

## Default gate limits

These come from one build and are starting points, shipped as `tools/default_limits.json`.

| Gate | Limit | Name in limits.json |
|---|---|---|
| Camera error at known points | 12 mm RMS for a view to be precise | `camera_rms_mm` |
| Precise views | at least 3 | `min_precise_views` |
| Overall dimensions | each within 10 mm of the maker's figure | `dimension_error_mm` |
| Outline against each precise view | median 3 px, 95th percentile 8 px, at 1600 px width | `outline_median_px`, `outline_p95_px`, `outline_ref_width_px` |
| Panel fairness away from creases | 99th percentile 2.5 degrees, maximum 5 degrees | `fairness_p99_deg`, `fairness_max_deg` |
| Part seating | step no more than 3 mm round the whole edge | `seating_step_mm` |
| Double skin | none | `double_skin_count` (0) |
| Separation (levels 2 and 3) | overlap no more than 0.5 mm | `separation_overlap_mm` |
