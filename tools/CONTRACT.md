# Tool contract

What each bundled tool takes and gives back, the files they share, and the gate limits.

## Ground rules

- Python 3.10 or newer. Plain tools need only NumPy, SciPy and Pillow (OpenCV is used when present).
- Tools marked **Blender** run inside Blender in background mode:
  `blender -b [file.blend] --python tools/<tool>.py -- <arguments>`.
- Every tool prints one line of usage when run with no arguments, writes its results as JSON beside any
  pictures, and exits 0 on success, 1 when a gate it measures fails, 2 on bad input.
- Units: millimetres in every file; Blender scenes are in metres.
- Vehicle coordinates: origin on the ground under the middle of the front axle; X toward the rear, Y toward
  the vehicle's right, Z up.
- Evidence renders use Cycles, because paint is judged by what it mirrors.

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
  out/work-<assembly>.blend  a builder's own trial assembly
  evidence/round-NN/   one frozen candidate: vehicle.blend, build.json, lit/ clay/ zebra/ closeups/ boards/,
                       the tools' JSON, gates.json, judge.md, marks.json, user-marks.md; at level 3 also
                       workshop.blend, build-workshop.json and exploded/
```

## File formats

Only the keys the tools read are fixed. Add others freely.

- **`vehicle.json`**: `maker`, `model`, `generation`, `years`, `trim`; `dimensions` with `length`, `width`
  (body, without mirrors), `height`, `wheelbase`, `track_front`, `track_rear`, `overhang_front`,
  `tyre_diameter_front|rear`, `tyre_width_front|rear`, `rim_diameter_front|rear`; `estimated`: a list of the
  dimensions above that were scaled off a drawing because the maker gave no figure; `points`: any further
  named point with its `[x, y, z]`. The named points below are worked out from the dimensions. A dimension
  nobody can supply is left out, and the points that need it are then not available. Estimated dimensions may
  be used to solve cameras and are left out of the dimension gate. `rim_diameter_*` is the rim's visible outer
  edge, where metal meets tyre, which is wider than the nominal wheel size; if only the nominal size is
  known, leave it out.
- **`landmarks.json`**: a list of `{ "view": name, "file": path, "crop": [u0, v0, u1, v1] (optional),
  "kind": "photo" | "drawing", "steer_deg": number, "focal_mm": number and "sensor_mm": number (optional, when
  the photo's data gives them), "points": { point name: [u, v] } }`. Pixels are measured
  from the top left of the whole file. Several views may share one file, each with its own `crop`: a blueprint
  sheet with four views is four entries. `steer_deg` is positive when the front wheels point toward the
  vehicle's right.
- **Pixels file** (for `rays.py --pixels` and `solve_cameras.py --triangulate`): a list of
  `{ "name": text, "view": name, "u": number, "v": number }`.

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
where the silhouette reaches furthest. A view needs at least six points spread across the picture; the tool
refuses fewer.

A photo is only as good as the depth its points cover. When every fully known point lies in one plane, as in
a face-on side photo showing two wheels, the direction solves and the distance does not. The solver checks
this and grades such a view `visual`, unless its focal length is given or it is a drawing. Three-quarter
photos, which see wheels on both sides, are the ones that solve well.
- **`cameras.json`**: per view: `kind` (`perspective` or `orthographic`), position, rotation, focal length,
  optical centre, image size, `steer_deg`, `rms_mm`, `rms_px`, `grade` (`precise` or `visual`).
- **`sources.json`**: per file: `file`, `url`, `licence`, `views` (a list: a blueprint sheet holds several),
  `variant_ok` (true or false), `shows`.
- **`finishes.json`**: `proof_look`: the look every round is judged under; `looks`:
  `{ look name: { "studio": preset, "slots": { slot: settings } } }`. Slots are free names such as `body`,
  `wheel`, `caliper`, `glass`, `trim`, `seat`. Settings: `base_color` `[r, g, b]`, `metallic`, `roughness`,
  `coat`, `coat_roughness`, `transmission`, `ior`, `emission` `[r, g, b]`, `emission_strength`. Studio presets,
  built by the kit: `soft` (large soft lights, for matt and pale finishes), `gloss` (hard-edged cards and
  strips for paint to mirror), `dark-paint` (large lit walls and a lit horizon so a dark body shows its
  outline).
- **`build.json`**: a list of `{ "assembly": name, "version": NN, "seats": [ { "part": name, "on": panel } ] }`
  in build order. `seats` lists only the parts that sit against a body panel (a lamp in its opening, a mirror
  on a door) with the panel each sits on, using the names the builders registered. Wheels and other parts
  that touch no panel are not listed.
- **`manifest.json`**: `assembly`, `version`, `sha256` of the module file, `depends_on`: the assemblies whose
  surface the module asks for (usually `["body"]`).
- **`parts.json`**: a list of `{ "part": name, "fixed_to": name, "pivot": [x, y, z], "level": 2 | 3,
  "basis": "measured" | "reconstructed" }`. The pivot here is the one that counts; builders pass it to
  `ctx.add`.
- **`marks.json`**: a list of `{ "n": number, "picture": path, "shape": "box" | "ellipse" | "outline",
  "points": [[u, v], ...] }`.
- **`limits.json`**: one number per gate, with the names used in `default_limits.json`.

## The kit

`tools/kit.py` is what every module's `build(ctx)` receives. Its docstrings are the reference. In short:

- `ctx.vehicle`, `ctx.mm(value)`: the dimensions, and millimetres to scene units.
- `ctx.add(obj, part=..., panel=False, separable=False, pivot=None)`: registers an object under the calling
  assembly. `panel=True` marks painted skin for the fairness and double-skin gates.
- `ctx.crease(obj, edges)`: marks edges that are real creases, so the fairness gate leaves them out.
- `ctx.material(slot)`: the material for a slot in the current look. Changing look changes no geometry.
- `ctx.body.hit(origin, direction)` and `ctx.body.nearest(point)`: where the body's surface is, for parts that
  must sit on it. Available to every assembly built after the body.
- `ctx.steerable(obj, side)`: registers a front wheel so a view can be rendered at its photo's steering angle.

## The tools

| Tool | Runs in | Input | Output |
|---|---|---|---|
| `solve_cameras.py` | Python | `vehicle.json`, `landmarks.json` | `cameras.json`. A photo solves to a perspective camera. A drawing solves to an orthographic one: scaled and placed from its landmarks. Each view, photo or drawing, is graded `precise` when its error at the known points is inside the camera limit, otherwise `visual`. Exit 1 when fewer than `--min-precise` views (default 3) are precise. With `--triangulate <pixels file>` it instead takes one feature seen in two or more solved views and prints its position on the vehicle and how far off it lands in each view. |
| `mask_photo.py` | Python | one view from `landmarks.json`; optional `--seed <render of the same view>` | `refs/masks/<view>.png` and a preview with the mask's edge drawn on the picture, to be checked by eye. A photo on a plain background works alone. A drawing works alone too: the mask is everything inside its outermost line, within the view's crop. A photo on a busy background needs `--seed`: a render of the model through that view's camera, which tells it roughly where the vehicle is. |
| `assemble.py` | Blender | `--build <file>` (default `data/build.json`); optional `--working <assembly>`; `--look <name>`; `--out` | Checks every accepted module against its manifest hash, runs each `build(ctx)` in order in a clean scene and saves the result. `--working <assembly>` takes that one module from `src/` in place of its accepted version, or after the listed ones if it is not in the list yet. Exit 1 on a hash mismatch or any module error. |
| `render_views.py` | Blender | scene, `cameras.json`, `--mode lit\|clay\|zebra`, `--look`, `--out`; optional `--view <name>` and `--trial` | One render per camera, or only the named view, at its picture's own size and steering angle. *Lit* is the look under its studio preset; *clay* is plain grey, to show shape without paint; *zebra* mirrors 40 stripes in the paint, to show ripples. An evidence run writes its sampling and device to `data/render.json` the first time and reads them from it afterwards, so every round matches. `--trial` is for builders: half size, few samples, and it neither reads nor writes `render.json`. |
| `compare.py` | Python | pictures, masks, renders, `cameras.json` | `boards/<view>.jpg` (picture beside render, same scale) and `outline.json`: median and 95th-percentile distance between the two silhouettes per view, scaled to a 1600 px wide image. Only precise views count toward the gate. |
| `dimensions.py` | Blender | scene, `vehicle.json` | `dimensions.json`: each dimension with its error in mm. |
| `closeups.py` | Blender | scene, `--size-mm` (default 600), `--mode`, `--look`, `--out`; optional `--hide <part>` | The **close-up ring**: close views covering both sides, front, rear and roof, named by position, with `closeups.json`. The tool checks that both sides are covered. |
| `fairness.py` | Blender | scene | `fairness.json`: for each panel, the angle between neighbouring faces at the 99th percentile and the maximum, leaving out marked creases. |
| `rays.py` | Blender | scene, `cameras.json`; `--grid N` (default 64: a 64 by 64 grid through each camera) or `--pixels <pixels file>` | `rays.json`: for each ray, every surface it passes through in order: object, material, position. With `--grid` it also lists every place where one painted panel lies within `--stack-mm` (default 10) behind another: a double skin. |
| `seating.py` | Blender | scene, and either `build.json` or `--part <name> --on <panel>` | `seating.json`: for each listed part, the signed step in mm between part and panel at points all round the part's edge. A builder uses the `--part` form on its own trial assembly. |
| `separation.py` | Blender | scene, `parts.json`, `--level 2\|3` | `separation.json`: each listed part is its own object with its pivot, and no two overlap by more than `--tolerance-mm` (default 0.5). Also renders an exploded view. |
| `annotate.py` | Python | a picture and `marks.json` | The marked picture, each mark numbered. |
| `gates.py` | Python | one `evidence/round-NN/` folder, `limits.json` | `gates.json` in that folder: every gate with its value, its limit and pass or fail, the overall result, and which limits differ from the defaults. |
| `wait_for.py` | Python | a file path and a timeout | Exit 0 when the file exists and has stopped changing, 1 on timeout. |

## Default gate limits

These come from one build and are starting points, shipped as `tools/default_limits.json`.

| Gate | Limit |
|---|---|
| Camera error at known points | 12 mm RMS for a view to be precise |
| Overall dimensions | each within 10 mm of the maker's figure |
| Outline against each precise view | median 3 px, 95th percentile 8 px, at 1600 px width |
| Panel fairness away from creases | 99th percentile 2.5 degrees, maximum 5 degrees |
| Part seating | step no more than 3 mm round the whole edge |
| Double skin | none |
| Separation (levels 2 and 3) | overlap no more than 0.5 mm |
