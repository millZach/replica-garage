# Blender: what works

Best practice for any vehicle. It holds only what a capable agent gets wrong without being told. Setting and
property names change between Blender versions: check them in the version you have.

If `vehicles/` has a note for this vehicle or one built like it, read that too.

## Surfaces

- **HARD RULE: Zero visible body ripples.** Absolutely no ripples are allowed on the body skin. If one shows up
  in lit, clay or zebra renders, diagnose the root cause before reshaping, fix the underlying surface, note why
  it happened and propose a skill improvement if one would prevent recurrence.
- **Build a panel from a few curves.** Describe each panel with a handful of curves, each with few control
  points, and fill between them to a regular grid of quads. A dense mesh pushed point by point onto a target
  ripples in ways local edge-angle checks miss and every reflection shows.
- **Decouple cutouts from continuous sweeps.** Never share control points between a recessed intake/opening
  and a continuous exterior shoulder or flank sweep; shared points pull visible dents into the painted skin.
- **Cut openings afterwards,** on a real edge loop in the surface. After any cut, check face direction: a
  flipped patch shades dark, and anything built from its normals afterwards, such as added thickness, tears
  open along its edge.
- **Stop the skin at the visible edge — and carry creases into their return.** A duct, an undercut or a recess
  is a separate part behind the panel. Folding one skin into a recess leaves creases and shards, while ending
  the painted return too soon lets the dark duct replace visible painted face below a crease.
- **A panel gap is geometry.** Build shut lines as a narrow gap of constant width along a curve, with a dark
  return inside. A drawn or textured line looks painted on.
- **Smooth shading with marked creases.** Shade panels smooth and mark only the real creases sharp. Those marks
  are also what the fairness gate leaves out, so mark them through the kit. Do not patch a curved region with
  flat ad-hoc strips — rebuild it as one fair skin.
- **Work in real size** and keep object scale applied, so the gates read millimetres.

## Parts

- **Lamps have depth and optical density.** Build the clear cover, the housing, the reflectors, optical facets
  and light sources as separate things at their real depths and spacing. Avoid wide empty dark gutters around
  inserts unless the reference shows them. Stop the cover from casting shadows, or the inside renders far too
  dark and speckled.
- **Glass has thickness** and is clear enough to see the cabin or engine bay through, unless the user chose
  dark glass. Check glazed openings from two angles so parallax exposes real depth underneath.
- **Wheels are built once** and placed four times. Tyres carry their sidewall detail; brakes sit behind the
  spokes at their real depth. Mark internal wheelhouse liners, inner brake hardware, engine bays, cabin parts
  and hidden underbody objects `exterior=False` in `ctx.add` so exterior coverage gates measure outer skin.
- **Close-up tactile details must survive native scale.** On perforated leather, separate the shading normals
  of steep hole walls from the flat lands and keep cut edges matte so highlights do not wash out the holes in
  shadow. Model stitching so the thread and seam channel sit proudly enough to read at normal viewing scale
  rather than sinking inside the leather mesh.
- **Graphics ride on the vehicle.** Place stripes, lettering, badges and procedural surface grain in the
  vehicle's own (Object) coordinates. Anything placed in world coordinates slides when the vehicle turns.

## Paint and materials

- **Gloss paint is colour under a clear coat:** full coat, very low coat roughness. A satin coat makes any
  colour read as matt.
- **Dark gloss shows every ripple; white and silver hide them.** Judge panels under the colour the user chose,
  and tell the user early if their colour is the demanding kind.
- **Differentiate interior and trim finishes.** Real cabins look believable because leather, perforated hide,
  stitching, brushed/satin metal, knurled controls, matte soft-touch plastic, glossy lacquer, carpet and gauge
  glass each catch light differently. Use `finishes.json` slot settings (`roughness`, `specular_ior_level`,
  `anisotropic`, `sheen`, and `surface` procedural micro-bump presets) so distinct materials never share one
  flat plastic highlight.

## Light

- **Gloss needs something to mirror.** Hard-edged light cards and strips with darkness between them make paint
  read as glossy. Soft, even light makes it read as plastic. Tune showroom card power, width and height in
  `finishes.json` (`showroom.cards`) when overhead cards bleach saturated paint on horizontal panels, and use
  `end_fill_watts` when recessed front/rear grilles or lamps fall too dark.
- **A dark vehicle needs lit surroundings.** Big lit walls and a lit horizon give it an outline. Thin lights in
  a black room lose the shape entirely. Dark wheels may need subtle low side fill (`showroom.cards.wheel_fill`)
  so spoke edges stay legible.
- **Light the cabin deliberately.** Exterior showroom cards barely enter a closed cabin. Use the `interior`
  studio preset (via `details.py`) for interior inspection views, and check closed-glass views under the
  exterior presentation style so glass reflections and cabin visibility both read naturally.
- **Diagnose reflections before blaming shape.** Hold the camera and exposure fixed, sweep a strip light
  across three angles (`details.py` `strip_angles_deg`) and toggle individual cards: a real dent stays pinned
  to the panel, while a lighting artefact moves or disappears.

## Rendering

- **Turn the graphics card on yourself.** In background mode Blender renders on the processor until a device
  is selected, both in its preferences and for the scene. The render tools do this when given a device and
  print the one actually used: read that line back.
- **Three qualities.** Trial renders: small and fast. Evidence renders: fixed settings, the same every round.
  Beauty renders: full size, more samples, denoised.
- **One colour setting for everything compared.** Lock `color_management` (`view_transform`, `look`,
  `exposure`) in `data/finishes.json` so every picture that sits beside another uses the exact same display
  transform.
- **Watch Cycles denoising on fine details.** Denoising blurs 1–2 px shadowed features (perforations,
  stitching, knurling, fine mesh, tyre lettering). When a modelled detail disappears in shadow, run an A/B
  pair with `details.py` (`denoise` on vs. off, and `toggle_part` on vs. off) to separate buried geometry from
  specular or denoiser washout.
- **Long lens, low camera.** For beauty pictures use a long lens from about hip height, with the vehicle
  filling the frame. A short lens up close bends the proportions the whole build was spent getting right.
- **Look from all round.** The ten views from `orbit.py` show speckled glass, floating parts and misplaced
  graphics that the reference photos' own viewpoints hide.

## The beauty set

Made for Stops 3 and 4 and the handover, in the style the user chose on the look card:

| Style | What it is | Suits |
|---|---|---|
| Dark showroom | Dark room, glossy dark floor, lit cards overhead and a lit ring on the floor | Any gloss paint; the default |
| Bright studio | Pale seamless backdrop, broad soft light, soft shadow under the vehicle | Matt and pale finishes, technical-looking pictures |
| Daylight | An outdoor sky image from a free, openly licensed source, saved under `refs/` and named as `sky` in `finishes.json`, on a plain ground | Seeing the vehicle as it would look outside |

Made with `orbit.py --beauty` (eight views from all round, two from above) and `closeups.py --style` for the
best details.
