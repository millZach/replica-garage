# Tools

The bundled tools of the replica-garage skill. What each takes, gives back and exits with is in
[CONTRACT.md](CONTRACT.md); each tool's own header gives its file formats and options, and every tool prints one
line of usage when run with no arguments.

| Tool | Runs in | For |
|---|---|---|
| `solve_cameras.py` | Python | Solve each reference photo's camera from points whose place on the vehicle is known. |
| `mask_photo.py` | Python | Cut the vehicle's silhouette out of a photo on a plain background, with a preview to check. |
| `render_views.py` | Blender | Render the model through every solved camera (lit, clay or zebra) at the photo's size. |
| `compare.py` | Python | Board each photo beside its render and measure how far apart the silhouettes are. |
| `dimensions.py` | Blender | Measure length, width, height, wheelbase and tracks against the maker's figures. |
| `closeups.py` | Blender | Render a ring of close views over both sides, front, rear and roof, and prove the coverage. |
| `fairness.py` | Blender | Measure the angle between neighbouring faces of each painted panel, away from real creases. |
| `rays.py` | Blender | List every surface a camera ray passes through, to find double skins, holes and poke-through. |
| `seating.py` | Blender | Measure the step between a part and its panel all round the part's edge. |
| `separation.py` | Blender | Check that parts which must come off are their own objects, pivot sensibly and do not overlap. |
| `annotate.py` | Python | Draw numbered boxes, ellipses and outlines on a picture for a fix note. |
| `merge.py` | Blender | Apply frozen, hashed accepted patches in order to a base scene. |
| `gates.py` | Python | Judge one round's evidence against the gate limits and write one overall result. |
| `wait_for.py` | Python | Wait until a file exists and has stopped changing. |

Blender tools run in background mode: `blender -b <file.blend> --python tools/<tool>.py -- <arguments>`.
`_common.py` and `_blender.py` hold shared code and are not run on their own.

## Install and test

```
python -m pip install -r tools/requirements.txt
python -m pytest tools/tests -q
```

The tests make their own small synthetic data: a box with known dimensions, synthetic cameras, drawn
silhouettes and tiny Blender scenes. The Blender tests find Blender through the `BLENDER` environment variable or
`blender` on `PATH`, run it headless one scene at a time, and are skipped when no Blender is found.
