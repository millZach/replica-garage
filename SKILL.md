---
name: replica-garage
description: Build an exact real vehicle in Blender from photos, blueprints and the maker's dimensions, as a manager directing builder and judge sub-agents. Use when asked to model a specific real car, truck, bike or other vehicle, or to make one that comes apart.
---

# Replica garage

You are the **manager**. You plan, hold the evidence, brief **builders** (one per assembly, at most three at
once) and a fresh **judge** each round, and you are the only one who talks to the user. Sub-agents run on your
own model and effort unless the user names another. If you cannot start sub-agents, read
[SOLO.md](SOLO.md) and follow the same steps alone.

Read on demand:

- [tools/CONTRACT.md](tools/CONTRACT.md): the project layout, every file's format, the kit builders code
  against, every tool and the gate limits. Read it now; the steps below name its files and tools. Every tool
  is run with `--project <the project folder>`; run with no arguments, it prints its usage.
- [BLENDER.md](BLENDER.md): best practice for modelling, paint, light and rendering, and the beauty set.
  Builders read it too. [vehicles/](vehicles/README.md) holds short notes on specific vehicles already built.
- [REFERENCES.md](REFERENCES.md): what to find and how to solve the cameras. Read at Step 2.
- [BRIEFS.md](BRIEFS.md): the common rules, builder brief, judge brief and fix note, to copy into every brief.
  Sub-agents cannot see this skill, so read it before writing one.
- [TAKE-APART.md](TAKE-APART.md): the three take-apart levels. Read before Stop 2.

## What holds for the whole build

- **One exact variant and spec.** Maker, model, generation, year, trim, visible factory options and operating
  states (lit vs. unlit lamps, glazed vs. opaque covers, roof/aero position, gauge layout) are fixed before
  anything is built.
- **Shape comes from measurement.** A drawing of the exact variant is solved as a flat camera and measured
  against like a photo. Photos are seen through their solved cameras. Depth and section thickness come from
  two or more views. Never rely on orthographic drawings alone when photographs exist.
- **Fair curves.** Every edge on a vehicle is a straight line, an arc or one smooth curve with few control
  points. Fit the curve to the measurements, then build the mesh on the curve. A fair edge outranks a closer
  outline match.
- **One skin.** Each painted panel is a single surface. A repair moves or replaces the old surface and joins
  edge to edge.
- **HARD RULE: Single Shared Boundary Function.** Every adjacent panel-to-panel or glass-to-body mating pair
  in `src/body.py` (and across assemblies via `ctx.publish_interface`) MUST derive both mating edges from the
  **same shared Python boundary function** (for example `hatch_front_edge(t)` and `cpillar_inner_edge(t)`)
  plus a constant `2–3 mm` shut-line offset — never two independently fitted splines or hand-edited coordinate
  lists. Every mating pair MUST run a build-time `assert` verifying that its generated edge vertices stay
  within `1.5–5.0 mm` gap and `<= 2.0 mm` flush step before `build(ctx)` returns, and declare the pair in
  `data/seams.json` so `seams.py` / `seating.py` verify the evaluated scene.
- **HARD RULE: No visible ripples on the body.** Absolutely no ripples are allowed to be visible on the body of
  a vehicle. If any ripple appears, find the root cause and address it, note why it happened (in `data/log.md`
  and the pass report), and if there is a way to improve this skill to prevent it from happening again, propose
  that improvement to the user.
- **Everything is code.** The vehicle is whatever `assemble.py` builds from the accepted modules. A fix is an
  edit to a module, and it counts once you have frozen it under `accepted/` with `tools/accept.py`.
- **Frozen candidate, locked cameras.** Every judgment is made on a saved copy no builder is changing,
  rendered through the exact same locked cameras (`--poses-from`), colour transform and exposure as the round
  before.
- **Gates measure, the eye approves; visibility beats count.** A gate is a number with a limit; a score is
  only a trend. A detail or blocking fault clears only when its own picture shows it clearly at native
  photographic scale, on both lit and shadowed sides. The user's sign-off comes last.
- **The user's choices are protected, narrowly.** What the user chose, or has seen and accepted, goes in
  `data/choices.md` in their words and is not a fault, whatever the photos show. Protect only the specific
  part, finish or option they approved; neighbouring surfaces remain open to review. Only the user may loosen
  a gate limit; record it there.
- **State survives restarts.** Keep `data/state.json` current with the active step, accepted module versions,
  current round, open owner marks and next action so a restart or context compaction resumes cleanly.
- **Blender runs in background mode.** Builders run trial renders (`render_views.py --trial`), one each. You
  alone run evidence renders, one at a time. With less than about 4 GB of memory free, wait or drop to one
  builder; check free disk space before heavy render rounds and use `--resume` when restarting a batch.
- **Reference material stays on this machine.** Free sources only; nothing found is copied into the model or
  published. A file whose licence is unclear goes to the user.

## Step 1: Set up

Ask the user where the project folder goes, or make it beside the current folder. Create the layout from the
contract and copy this skill's `tools/` and `BLENDER.md` into it, with the note from `vehicles/` if there is
one for this vehicle or one built like it. Find Blender; install `tools/requirements.txt`; check the
graphics card, free memory and disk. Start `data/log.md` (recording this skill's path and revision) and
`data/state.json`, and confirm to the user that setup succeeded.

Done when: a one-cube test render comes back from background Blender on the device you will use.

## Step 2: References, then the first stop

Follow [REFERENCES.md](REFERENCES.md).

**Stop 1.** Show the user the whole set: every picture and drawing, the dimensions, which views will be
measured, any divergent factory options or regional trim across the photos, what is missing and what that
will cost in accuracy, and any file whose licence is unclear. Wait for their yes.

Done when: the user has approved the set, and `refs/sources.json` and `data/vehicle.json` are complete.

## Step 3: Solve the cameras

Write `data/landmarks.json`, run `solve_cameras.py`, and make a mask for each precise view that has a plain
background (for drawings with dashed outlines, use `mask_photo.py --close-px`). A precise view with a busy
background gets its mask after the first build, seeded from a render.

Done when: at least three views are precise and between them they see the front, the rear and one side,
**and** `data/cameras.json` also includes at least two perspective reference photographs (front three-quarter
and rear three-quarter, plus any key straight-rear or straight-front hero photo, even when graded `visual`
for lack of lens data or studio symmetry). Drawings alone cannot expose depth, recessed enclosures, lamp
optics or surface ripples. If the references cannot give three precise views, say so at once: the user
chooses between finding more, or going on with the weaker views named as estimates.

## Step 4: The plan and the look card

Write `data/plan.md`:
- the assemblies, who builds each, and the order;
- a **Feature Ledger** listing every visually defining exterior and interior feature (lamps, grilles/intakes,
  glazed openings, vents, wheels/brakes, exhaust/diffuser, roof/bonnet features, cockpit landmarks): its
  reference photo, what makes it visually recognizable (depth, spacing, overlap, finish — not just a count),
  and the **single integration owner** responsible for proving the installed junction when multiple assemblies
  meet there;
- a **Small-Details Checklist** (fuel/charge flaps, side markers, cowl vents, wipers, badges/scripts,
  fasteners, trim gaps) tracked persistently so small details are not starved by the judge's top-15 list.

**Stop 2: the look card.** Before any surface work, ask the user:

1. **Colours and finishes**, in words: body, wheels, brake calipers, trim, interior, glass tint. Offer the
   maker's own launch colours first.
2. **Factory options and operating states:** explicitly resolve any visible differences found across the
   references (transparent vs. opaque covers, running lights/headlamps on vs. off, roof/spoiler stowed vs.
   deployed, gauge layout, regional markers/trim).
3. **Number plates and badges:** kept, customised, or left off. Note that any bespoke non-factory item
   (custom plate, livery, aftermarket wheel) will get two quick on-car finish options before freezing.
4. **The cabin:** **full photo-matched cabin** (required for interior close-ups, cabin walkthroughs/films,
   and take-apart levels 2–3), **visible through glass only** (built to read through closed exterior windows;
   not judged against cockpit close-up photos), or **dark glass and no cabin**.
5. **How far it comes apart:** level 1, 2 or 3, with the cost of each from [TAKE-APART.md](TAKE-APART.md).
6. **How it is shown:** dark showroom (default), bright studio or daylight, from [BLENDER.md](BLENDER.md).
7. **The team:** how many builders at once (default three; one on a small machine) and on which model
   (default: yours).

Tell them what to expect: days of agent time. The build this skill came from cost about $590 at API prices
for the first finished car and about $1,070 with the fixes that followed.

Write the answers to `data/choices.md`. Write each colour set as a look in `data/finishes.json`, give each
its studio preset (`gloss` for shiny paint, `dark-paint` for a dark body, `soft` otherwise), explicit
`color_management` (`view_transform`, `look`, `exposure`), `style` (`showroom`, `studio` or `daylight`), and
name the **proof look**: the final paint. Write initial named exterior close-up cameras for the Feature Ledger
to `data/details.json`. For level 2 or 3, write `data/parts.json` now.

Done when: those files are written and `data/state.json` is updated.

## Step 5: The first build

Brief one builder per assembly from [BRIEFS.md](BRIEFS.md), body first, since other parts ask the body where
its surface and cut apertures are (`ctx.body` and `ctx.interface`):

- **Body:** the painted shell, fenders, arches, shut lines, openings (deriving every adjacent panel/glass
  mating edge from a single shared Python boundary function plus `2–3 mm` shut-line offset with a build-time
  `assert`, declaring body/glass seam pairs in `data/seams.json`, and publishing aperture loops with
  `ctx.publish_interface`).
- **Front and rear ends:** lamps, grilles, ducts, the dark parts of the bumpers, lower aero, badges/plates.
- **Hardware:** wheels, tyres, brakes, mirrors, wipers, spoilers and anything bolted on (marking internal
  wheelhouse liners, inner brakes and engine-bay parts `exterior=False` in `ctx.add`).
- **Glass:** every pane, as its own part.

Save each brief as `notes/<assembly>/brief-00.md`, copying in that assembly's entries from the Feature Ledger
and Small-Details Checklist. Wait for each report with `wait_for.py`. As each `pass-00.md` arrives, verify its
matched-angle photo crops and depth proofs, freeze the module with `tools/accept.py` (which writes
`accepted/<assembly>/00/`, its `manifest.json` hash and updates `data/build.json`), and run `assemble.py`.
Render the whole vehicle through the solved cameras as soon as the body exists, and again as each assembly
joins it.

**Early paint & bespoke check (right after `body` pass 00, before locking later rounds):** Render 2–3 paint
and exposure swatches on the actual body under the chosen presentation style, comparing panel midtones (away
from glare) against the reference photos. If the user asked for a bespoke item (custom plate, livery), show
two on-car options once its assembly lands. Confirm the chosen look and record its exact RGB and exposure in
`data/choices.md` and `data/finishes.json`. Once the wheels exist, set each photo's `steer_deg` so the
rendered front rims match the photo, and solve the cameras again.

Done when: `assemble.py` builds `out/vehicle.blend` from the accepted modules, all four assemblies are in it,
and the proof look renders cleanly.

## Step 6: The judge loop

Run this loop before each showing of the vehicle to the user (Stops 3 and 4). Keep raw un-judged WIP renders
out of formal review until the loop runs. Round numbers run on through the whole build; each run of the loop
has its own baseline and its own three fix rounds.

1. **Freeze.** Copy `out/vehicle.blend`, `data/build.json` and `data/cameras.json` into the next
   `evidence/round-NN/`; at level 3 the workshop copy and its build list too. Run `render_views.py` in lit,
   clay and zebra (use `--resume` if interrupted), `orbit.py` and `closeups.py` under the proof look (pass
   `--poses-from` pointing at the baseline round's `orbit.json` / `closeups.json` from the second round onward
   so cameras stay pixel-locked), and `details.py` for the Feature Ledger and cabin views. Then run
   `compare.py`, `compare_zones.py` (building the 1:1 Hero Zone Comparison Sheet `<round>/hero-zones.jpg` for
   front headlamps & nose, rear hatch glass & tail lamps, roofline/B-pillar/quarter window, rear
   quarter-to-bumper seam, and full side profile, configurable via `data/zones.json`), `dimensions.py`,
   `fairness.py`, `seating.py`, `seams.py` (for body-to-body & glass-to-body seam gaps/flush), `daylight.py`
   (fast CPU daylight-leak ray gate across `front`, `rear`, `left`, `right`, and `3/4` views), `rays.py --grid`,
   and for levels 2 and 3 `separation.py`. Run `gates.py` last.
2. **Judge (Strict 2-Stage "Macro First" Gate).** Start a fresh judge with the judge brief. Tell it which
   assemblies are not built yet and point it to `data/plan.md`'s Feature Ledger and Small-Details Checklist.
   - **Stage 1 (5-second macro triage — 5 images only):** Before inspecting cabin gauges, wheels, decals, or
     close-ups, the judge looks ONLY at `front`, `rear`, `left`, `front-left`, `rear-right` beside the
     reference photos (plus `hero-zones.jpg`) and records 4 binary PASS/FAIL checks in `macro-triage.json` and
     at the top of `judge.md`:
     1. Lamp shapes/angles match reference?
     2. Zero open gaps/daylight leaks between panels or glass?
     3. Smooth continuous roofline/greenhouse with zero steps?
     4. Flush panel-to-panel alignment?
   - **Any FAIL blocks Stage 2 detail work** and caps assembly scores (`<= 55/100`) until fixed. When Stage 1
     fails, do NOT brief or accept cabin/wheel/decal/detail passes — fix the macro faults first (`accept.py
     --round evidence/round-NN` enforces this block automatically).
   - **Stage 2 (only when all 4 Stage 1 checks PASS):** Full inspection of close-ups, Feature Ledger, cabin,
     wheels, decals and Small-Details Checklist. It returns `macro-triage.json`, `judge.md` and `marks.json`:
     ranked **marked faults** (blocking or minor), a checklist status for small details, and a score per
     assembly. Run `annotate.py` to draw the marks.
3. **The first round of the loop is the baseline.** Later rounds are measured against it. Faults the user
   marked at the last stop go into every round's brief until cleared in their original locked camera and box,
   ahead of the judge's faults — **merged with** (not replacing) top blocking judge faults so major misses do
   not stall across rounds.
4. **Fix.** Write one fix note per assembly, each on one marked area, worst blocking faults first (batching
   quick Small-Details Checklist items onto the owning assembly once Stage 1 passes). Assemblies work in
   parallel. Send the note to the builder that owns the assembly if it can be continued; otherwise start a
   fresh one with the common rules, the note and its earlier passes. Ask for the cause before the fix when a
   fault looks like a symptom. Check each pass against its reference / before / after proof and regression
   view, then freeze it with `tools/accept.py --round evidence/round-NN` (updating every build list that names
   it, and enforcing the Stage 1 macro block on detail assemblies), or return it.
5. **Rebuild** with `assemble.py`, update `data/state.json`, and go to 1.

Run at most three fix rounds after the baseline. Stop sooner when every gate passes, the Small-Details
Checklist is clear, and the judge lists no blocking fault. Then show the user regardless: the trend from the
baseline, and exactly what still fails.

## Step 7: The first whole-vehicle pictures

**Stop 3.** Show the beauty set in the chosen style, the boards for **every** solved view (drawings and
perspective photos), hero close-ups from `details.py`, a few views from the close-up ring, the gate table,
and stills of each look on the real shape. Present pictures so the user can inspect them directly (inline
images or a tested gallery reachable from their device). Say which assemblies are still to come. Ask what to
change and confirm the colours.

Done when: the user has answered, and their marks are in `evidence/round-NN/user-marks.md` (with exact pixel
boxes and source cameras) as faults for the next round, ahead of the judge's.

## Step 8: Finish

Work the user's marks first, plus any open Small-Details Checklist items. Brief the new assemblies:
- **Cabin** (marking interior objects `exterior=False` in `ctx.add`): for a full photo-matched cabin, add a
  **Cabin Evidence Pack** to `data/details.json` before judging — seated driver's-eye view, matched interior
  reference views (dash/cockpit, seats/headrests, steering wheel from two angles, centre console/switchgear,
  door card/sill) using logged per-view `hide` cutaway lists under the `interior` studio preset, closed-glass
  exterior-to-interior views with nothing hidden, and `targets_mm` sightline ray-checks proving dials and
  control legends are legible from the reference seats.
- **Underbody** (marking hidden floorpan/wheelhouses `exterior=False`, while checking sightlines through open
  diffusers and wheel openings).
- For levels 2 and 3, one assembly for each group of parts a removed panel uncovers, and for level 3 the
  mechanical assemblies of the workshop copy.

Lamp insides and badges go as fix notes to the assembly that owns them. Then run the judge loop again. Look
along every edge in the hero details and close-up ring yourself before the judge does.

Done when: the judge loop has ended and you have looked at every hero detail and close-up.

## Step 9: The final close-ups

**Stop 4.** Show the beauty set, the hero detail comparisons (including cabin and micro-details at native
photo scale), the close-up ring, the boards for every view and the gate table. List every fault still open
and why. Ask for sign-off or more marks; more marks mean another run of Step 8.

On sign-off, build a ready-to-open showroom file with `tools/showroom.py` (embedding the proof look, colour
management, presentation style and framing camera) and write `data/handoff.json` (accepted `.blend` paths,
proof look, colour management, lamp and option states, and key dynamic/separable part or material names such
as wheels, lamp emitters, gauge needles and door glass so downstream rendering or video tools can pick up the
car cleanly). Hand over: `out/vehicle.blend`, `out/vehicle-showroom.blend` and how to rebuild them,
`data/handoff.json`, the looks, what was measured and what was estimated, the open faults, the beauty set,
and the time and usage from `data/log.md`. Levels 2 and 3 add what [TAKE-APART.md](TAKE-APART.md) lists for
this stop. Write the vehicle note described in [vehicles/](vehicles/README.md).

## When something will not come right

| What you see | Do this first |
|---|---|
| You and the user, or two builders, read a photo differently | A measure-only pass: change nothing; find the feature's pixel in two or three views and run `solve_cameras.py --triangulate` to see where it sits and where it lands in the others |
| A part and the body are both wrong in one picture | Render the part alone, then the body alone |
| A panel looks dented or shows a bright patch | Hold camera and exposure fixed; sweep a strip light across three angles (`details.py` `strip_angles_deg`) and toggle individual overhead cards. A real dent stays pinned to the panel; a light-card artefact moves or vanishes |
| A highlight looks wrong on glass or a lamp | `rays.py --pixels`: find the first surface and what it mirrors |
| A crease lands in the right pixels but the face below looks wrong | Trace the crease into its adjacent face in two views and run `rays.py --pixels` to separate dark-shaded paint from a black duct behind it |
| A modelled micro-detail (stitching, perforations, mesh, legends) disappears | Render an A/B pair at native photo scale on **both** lit and shadowed sides with `details.py` (`toggle_part` ON vs. OFF, `denoise` ON vs. OFF) to distinguish buried geometry from specular/denoiser washout |
| Raising or moving a part hides a neighbouring control or gauge | Cast sightlines from the driver's eye and reference seat cameras (`details.py --sightlines`), checking each individual legend — physical clearance alone does not prove visibility |
| A fix keeps moving the kink to its own edge | Rebuild the whole panel as one surface between measured curves; decouple cutout control points from continuous shoulder sweeps |
| A fix looked right and broke its neighbour | Put the neighbour back to its last accepted version |
| The same fault survives two rounds | Go through every reference file again; an unused one shows it |
| A gate passes and the picture still looks wrong | Trust the picture, and write down what the gate missed |
