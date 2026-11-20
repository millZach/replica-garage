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

- **One exact variant.** Maker, model, generation, year and trim are fixed before anything is measured.
- **Shape comes from measurement.** A drawing of the exact variant is solved as a flat camera and measured
  against like a photo. Photos are seen through their solved cameras. Depth comes from two or more views.
- **Fair curves.** Every edge on a vehicle is a straight line, an arc or one smooth curve with few control
  points. Fit the curve to the measurements, then build the mesh on the curve. A fair edge outranks a closer
  outline match.
- **One skin.** Each painted panel is a single surface. A repair moves or replaces the old surface and joins
  edge to edge.
- **Everything is code.** The vehicle is whatever `assemble.py` builds from the accepted modules. A fix is an
  edit to a module, and it counts once you have frozen it under `accepted/`.
- **Frozen candidate.** Every judgment is made on a saved copy no builder is changing, rendered through the
  same cameras with the same settings as the round before.
- **Gates measure, the eye approves.** A gate is a number with a limit; a score is only a trend. A blocking
  fault clears when its own picture shows it gone. The user's sign-off comes last.
- **The user's choices are protected.** What the user chose, or has seen and accepted, goes in
  `data/choices.md` in their words and is not a fault, whatever the photos show. Only the user may loosen a
  gate limit; record it there.
- **Blender runs in background mode.** Builders run trial renders (`render_views.py --trial`), one each. You
  alone run evidence renders, one at a time. With less than about 4 GB of memory free, wait or drop to one builder.
- **Reference material stays on this machine.** Free sources only; nothing found is copied into the model or
  published. A file whose licence is unclear goes to the user.

## Step 1: Set up

Ask the user where the project folder goes, or make it beside the current folder. Create the layout from the
contract and copy this skill's `tools/` and `BLENDER.md` into it, with the note from `vehicles/` if there is
one for this vehicle or one built like it. Find Blender; install `tools/requirements.txt`; check the
graphics card, free memory and disk. Start `data/log.md`.

Done when: a one-cube test render comes back from background Blender on the device you will use.

## Step 2: References, then the first stop

Follow [REFERENCES.md](REFERENCES.md).

**Stop 1.** Show the user the whole set: every picture and drawing, the dimensions, which views will be
measured, what is missing and what that will cost in accuracy, and any file whose licence is unclear. Wait for
their yes.

Done when: the user has approved the set, and `refs/sources.json` and `data/vehicle.json` are complete.

## Step 3: Solve the cameras

Write `data/landmarks.json`, run `solve_cameras.py`, and make a mask for each precise view that has a plain
background. A precise view with a busy background gets its mask after the first build, seeded from a render.

Done when: at least three views are precise and between them they see the front, the rear and one side. A
face-on photo rarely grades precise by itself; three-quarter photos and drawings do. If the references cannot
give three, say so at once: the user chooses between finding more, or going on with the weaker views named as
estimates.

## Step 4: The plan and the look card

Write `data/plan.md`: the assemblies, who builds each, and the order.

**Stop 2: the look card.** Before any surface work, ask the user:

1. **Colours and finishes**, in words: body, wheels, brake calipers, trim, interior, glass tint. Offer the
   maker's own launch colours first.
2. **Number plates and badges:** kept or left off.
3. **The cabin:** fully detailed, only what shows through the glass, or dark glass and no cabin. Levels 2 and
   3 below need a cabin.
4. **How far it comes apart:** level 1, 2 or 3, with the cost of each from [TAKE-APART.md](TAKE-APART.md).
5. **How it is shown:** dark showroom (default), bright studio or daylight, from [BLENDER.md](BLENDER.md).
6. **The team:** how many builders at once (default three; one on a small machine) and on which model
   (default: yours).

Tell them what to expect: days of agent time. The build this skill came from cost about $590 at API prices
for the first finished car and about $1,070 with the fixes that followed.

Write the answers to `data/choices.md`. Write each colour set as a look in `data/finishes.json`, give each its
studio preset (`gloss` for shiny paint, `dark-paint` for a dark body, `soft` otherwise), set `style` to
`showroom`, `studio` or `daylight`, and name the **proof look**: the final paint. For level 2 or 3, write `data/parts.json` now.

Done when: those files are written.

## Step 5: The first build

Brief one builder per assembly from [BRIEFS.md](BRIEFS.md), body first, since other parts ask the body where
its surface is:

- **Body:** the painted shell, fenders, arches, shut lines, openings.
- **Front and rear ends:** lamps, grilles, ducts, the dark parts of the bumpers, lower aero.
- **Hardware:** wheels, tyres, brakes, spoilers and anything bolted on.
- **Glass:** every pane, as its own part.

Save each brief as `notes/<assembly>/brief-00.md` and name in it the best reference close-up for each
intricate feature. Wait for each report with `wait_for.py`. As each `pass-00.md` arrives, freeze the module
under `accepted/<assembly>/00/`, add it to `data/build.json` (taking `seats` from the report's list of parts
that sit on a panel) and run `assemble.py`. Render the whole vehicle through the solved cameras as soon as the body
exists, and again as each assembly joins it. Once the wheels exist, set each photo's `steer_deg` so the
rendered front rims match the photo, and solve the cameras again.

Done when: `assemble.py` builds `out/vehicle.blend` from the accepted modules, all four assemblies are in it,
and the proof look renders.

## Step 6: The judge loop

Run this loop before each showing of the vehicle to the user (Stops 3 and 4). Round numbers run on through the
whole build; each run of the loop has its own baseline and its own three fix rounds.

1. **Freeze.** Copy `out/vehicle.blend` and `data/build.json` into the next `evidence/round-NN/`; at level 3
   the workshop copy and its build list too. Run `render_views.py` in lit, clay and zebra, `orbit.py` and
   `closeups.py` under the proof look, then `compare.py`, `dimensions.py`, `fairness.py`, `seating.py`, `rays.py --grid`,
   and for levels 2 and 3 `separation.py`. Run `gates.py` last.
2. **Judge.** Start a fresh judge with the judge brief. Tell it which assemblies are not built yet. It returns
   `judge.md` and `marks.json`: ranked **marked faults**, each blocking or minor, and a score per assembly.
   Run `annotate.py` to draw the marks.
3. **The first round of the loop is the baseline.** Later rounds are measured against it. Faults the user
   marked at the last stop go into every round's brief until they are gone.
4. **Fix.** Write one fix note per assembly, each on one marked area, worst blocking faults first. Assemblies
   work in parallel. Send the note to the builder that owns the assembly if it can be continued; otherwise
   start a fresh one with the common rules, the note and its earlier passes. Ask for the cause before the fix
   when a fault looks like a symptom. Check each pass against its own proof, then freeze it under `accepted/`
   with the pass's own number and update `data/build.json`, or return it.
5. **Rebuild** with `assemble.py` and go to 1.

Run at most three fix rounds after the baseline. Stop sooner when every gate passes and the judge lists no
blocking fault. Then show the user regardless: the trend from the baseline, and exactly what still fails.

## Step 7: The first whole-vehicle pictures

**Stop 3.** Show the beauty set in the chosen style, the board for every view, a few views from the close-up
ring, the gate table, and stills of each look on the real shape. Say which assemblies are still to come. Ask what to change and confirm the
colours.

Done when: the user has answered, and their marks are in `evidence/round-NN/user-marks.md` as faults for the
next round, ahead of the judge's.

## Step 8: Finish

Work the user's marks first. Brief the new assemblies: the cabin as chosen, the underbody, for levels 2 and 3
one assembly for each group of parts a removed panel uncovers, and for level 3 the mechanical assemblies of
the workshop copy. Lamp insides and badges go as fix notes to
the assembly that owns them. Then run the judge loop again. Look along every edge in every view of the
close-up ring yourself before the judge does.

Done when: the judge loop has ended and you have looked at every close-up.

## Step 9: The final close-ups

**Stop 4.** Show the beauty set, the close-up ring, the board for every view and the gate table. List every fault still open and
why. Ask for sign-off or more marks; more marks mean another run of Step 8.

On sign-off, hand over: `out/vehicle.blend` and how to rebuild it, the looks, what was measured and what was
estimated, the open faults, the beauty set, and the time and usage from `data/log.md`. Levels 2 and 3 add
what [TAKE-APART.md](TAKE-APART.md) lists for this stop. Write the vehicle note described in
[vehicles/](vehicles/README.md).

## When something will not come right

| What you see | Do this first |
|---|---|
| You and the user, or two builders, read a photo differently | A measure-only pass: change nothing; find the feature's pixel in two or three views and run `solve_cameras.py --triangulate` to see where it sits and where it lands in the others |
| A part and the body are both wrong in one picture | Render the part alone, then the body alone |
| A panel looks dented | Match the photo's light before reshaping anything |
| A highlight looks wrong on glass or a lamp | `rays.py --pixels`: find the first surface and what it mirrors |
| A fix keeps moving the kink to its own edge | Rebuild the whole panel as one surface between measured curves |
| A fix looked right and broke its neighbour | Put the neighbour back to its last accepted version |
| The same fault survives two rounds | Go through every reference file again; an unused one shows it |
| A gate passes and the picture still looks wrong | Trust the picture, and write down what the gate missed |
