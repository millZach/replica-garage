# Tools

The bundled tools of the replica-garage skill. What each takes, gives back and exits with, and every shared file
format, is in [CONTRACT.md](CONTRACT.md); each tool's own header gives its options. Every tool prints one line of
usage when run with no arguments.

| Tool | Runs in | For |
|---|---|---|
| `solve_cameras.py` | Python | Solve each photo's camera (and each drawing's flat camera) from known points, grade each view, triangulate a feature. |
| `mask_photo.py` | Python | Make a view's silhouette mask: plain background, drawing, or seeded from a render. |
| `assemble.py` | Blender | Build the vehicle from the accepted, hash-checked modules in build order. |
| `render_views.py` | Blender | Render the model through every solved camera (lit, clay or zebra) at the picture's size and steering angle. |
| `compare.py` | Python | Board each picture beside its render and measure how far apart the silhouettes are. |
| `dimensions.py` | Blender | Measure length, width, height, wheelbase, tracks and overhang against the maker's figures. |
| `closeups.py` | Blender | Render the close-up ring over both sides, front, rear and roof, and prove the coverage. |
| `fairness.py` | Blender | Measure the angle between neighbouring faces of each painted panel, away from marked creases. |
| `rays.py` | Blender | List every surface camera rays pass through, and find double skins. |
| `seating.py` | Blender | Measure the step between each seated part and its panel all round the part's edge. |
| `separation.py` | Blender | Check that parts which come off are their own objects with their pivots and do not overlap. |
| `annotate.py` | Python | Draw the numbered marks from marks.json on a picture. |
| `gates.py` | Python | Judge one round's evidence against the gate limits and write one overall result. |
| `wait_for.py` | Python | Wait until a file exists and has stopped changing. |

Also here: `kit.py`, what every module's `build(ctx)` receives and the studio presets; `default_limits.json`, the
starting gate limits; `_common.py` and `_blender.py`, shared code that is not run on its own.

Blender tools run in background mode: `blender -b [file.blend] --python tools/<tool>.py -- <arguments>`. Tools
find the project as the folder above `tools/`, or take `--project`.

## Install and test

```
python -m pip install -r tools/requirements.txt
python -m pytest tools/tests -q
```

The tests make their own small synthetic data: a box with known dimensions, synthetic cameras and a drawing,
drawn silhouettes, and tiny Blender scenes registered through the kit. The Blender tests find Blender through the
`BLENDER` environment variable or `blender` on `PATH`, run it headless one scene at a time, and are skipped when
no Blender is found.
