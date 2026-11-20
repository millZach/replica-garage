# Taking the vehicle apart

Ask at Stop 2 which level the user wants. Each level includes the one before.

| Level | What comes off | What it adds to the build |
|---|---|---|
| **1. Exterior** (default) | Nothing. Doors, bonnet and wheels are separate objects but the vehicle is built to be seen whole. | Nothing |
| **2. Panels and wheels** | Doors, bonnet, boot or engine cover, bumpers, fenders and wheels lift away. Behind them: door shuts and inner panels, the cabin, brakes and hubs, the suspension you can see through an arch, the engine as seen with its cover open. | Roughly half as much work again. Every surface a removed panel uncovers has to exist. |
| **3. Full teardown** | Everything, down to the bare body shell: engine and its internals, gearbox, suspension, steering, exhaust, fuel tank, wiring runs, seats and trim. | About as much work again as the whole exterior, often more. Free references for hidden parts are thin. |

Tell the user both costs before they choose.

## How to build for it

- **Level 3 is a separate workshop copy.** Keep the assembled vehicle as the master: it holds everything seen
  with the vehicle whole or with a panel open. The workshop copy has its own build list,
  `data/build-workshop.json`, written in Step 8 when the first mechanical assembly is accepted. It starts as a
  copy of `data/build.json`. Each mechanical assembly is then added to it, and where the master has a simpler
  stand-in for the same thing (an engine modelled only as seen with its cover open), the full assembly takes
  the stand-in's place in the workshop list instead of joining it. Build it with
  `assemble.py --build data/build-workshop.json --out out/workshop.blend`.
- **One accept, every list.** When a pass is accepted, set its version in every build list that names the
  assembly. That is how a fix to the body reaches both copies.
- **Find the teardown references once the level is known.** If the user chose level 2 or 3 at Stop 2, look for
  cutaways, parts diagrams and workshop pictures then, and show the user what you found before Step 8.
- **Decide the part list at Stop 2.** Write every part that must come off in `data/parts.json` before the
  first build: what it is fixed to (another part in the list, or `shell` for the body that never comes off),
  the assembly that will build it, and its pivot where the real hinge, hub or mounting is. Each is its own
  object.
- **A removed panel shows its back.** From the first build, each removable panel has thickness, a returned
  edge and an inner face, marked as inner through the kit so the skin gates look only at the painted outside.
  The one-skin rule still holds for that outside. What the panel uncovers is built in Step 8.
- **Measured or reconstructed.** Hidden parts rarely have photos from known angles. Build them from the
  maker's figures (bore, stroke, cylinder count and layout, gear count, suspension type) and from cutaways and
  parts diagrams. Mark each part *measured* or *reconstructed* in `data/parts.json`, and tell the user which
  is which at the final stop.
- **Count before you build.** Bolts, ribs, pipes, fins: count them in the best reference and write the count
  down.

## Gates

Run `separation.py` at each judge round with the chosen level: on the vehicle until the workshop copy exists,
then on the workshop copy, which is frozen into the same round folder. The tool checks that every listed part
is its own object with its pivot, and that no two separable parts overlap by more than the limit. A part whose
assembly is not in the build yet is reported as not built and does not fail the gate. It also renders an
exploded view.

At Stop 4 show the exploded view with the close-ups, and give the user the list of parts marked measured and
reconstructed. The handover includes `out/workshop.blend` and its build list.

The judge brief has two slots for this. Extra evidence: the exploded view, and `closeups.py --hide <part>` for
each uncovered area. Extra instructions: "Parts marked reconstructed in data/parts.json are judged for being
plausible, complete and cleanly built, not for matching a photo."
