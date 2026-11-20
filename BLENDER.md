# Blender: what works

Best practice for any vehicle. It holds only what a capable agent gets wrong without being told. Setting and
property names change between Blender versions: check them in the version you have.

If `vehicles/` has a note for this vehicle or one built like it, read that too.

## Surfaces

- **Build a panel from a few curves.** Describe each panel with a handful of curves, each with few control
  points, and fill between them to a regular grid of quads. A dense mesh pushed point by point onto a target
  ripples in ways no number catches and every reflection shows.
- **Cut openings afterwards,** on a real edge loop in the surface. After any cut, check face direction: a
  flipped patch shades dark, and anything built from its normals afterwards, such as added thickness, tears
  open along its edge.
- **Stop the skin at the visible edge.** A duct, an undercut or a recess is a separate part behind the panel.
  Folding one skin into a recess leaves creases and shards.
- **A panel gap is geometry.** Build shut lines as a narrow gap of constant width along a curve, with a dark
  return inside. A drawn or textured line looks painted on.
- **Smooth shading with marked creases.** Shade panels smooth and mark only the real creases sharp. Those marks
  are also what the fairness gate leaves out, so mark them through the kit.
- **Work in real size** and keep object scale applied, so the gates read millimetres.

## Parts

- **Lamps have depth.** Build the clear cover, the housing, the reflectors and the light sources as separate
  things at their real depths. Stop the cover from casting shadows, or the inside renders far too dark and
  speckled.
- **Glass has thickness** and is clear enough to see the cabin through, unless the user chose dark glass.
- **Wheels are built once** and placed four times. Tyres carry their sidewall detail; brakes sit behind the
  spokes at their real depth.
- **Graphics ride on the vehicle.** Place stripes, lettering and badges in the vehicle's own coordinates.
  Anything placed in the room's coordinates slides when the vehicle turns.

## Paint

- **Gloss paint is colour under a clear coat:** full coat, very low coat roughness. A satin coat makes any
  colour read as matt.
- **Dark gloss shows every ripple; white and silver hide them.** Judge panels under the colour the user chose,
  and tell the user early if their colour is the demanding kind.

## Light

- **Gloss needs something to mirror.** Hard-edged light cards and strips with darkness between them make paint
  read as glossy. Soft, even light makes it read as plastic.
- **A dark vehicle needs lit surroundings.** Big lit walls and a lit horizon give it an outline. Thin lights in
  a black room lose the shape entirely.
- **Match the photo's light before blaming the shape.** A panel that looks dented beside its reference is often
  lit from a different side.

## Rendering

- **Turn the graphics card on yourself.** In background mode Blender renders on the processor until a device
  is selected, both in its preferences and for the scene. The render tools do this when given a device and
  print the one actually used: read that line back.
- **Three qualities.** Trial renders: small and fast. Evidence renders: fixed settings, the same every round.
  Beauty renders: full size, more samples, denoised.
- **One colour setting for everything compared.** Keep the same view transform, look and exposure for every
  picture that will sit beside another.
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
