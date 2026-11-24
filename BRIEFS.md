# Briefs

Sub-agents see only what you send them. Start every brief with **Common rules**, then add the brief for the
role. Fill in the parts in `<angle brackets>`; a slot you do not need is deleted. Point at files instead of
pasting their contents.

## Common rules (every brief)

```
You are working on an exact model of <maker, model, generation, year, trim> in Blender.

Project folder: <path>. Read tools/CONTRACT.md there first: it gives the layout, every file's format, the kit
(the ctx your code receives), every tool and the gate limits. Then read BLENDER.md there<, and the note on
this vehicle, <file>>.
References: refs/photos and refs/blueprints, described in refs/sources.json. Use them as a guide only; copy
nothing from them into the model. Solved cameras: data/cameras.json. Dimensions: data/vehicle.json.
The owner's choices: data/choices.md. Anything listed there is intended and is not a fault.

How shape and appearance are decided:
- Measure against the solved views in data/cameras.json (both drawings and perspective photographs): render
  through a view's camera and compare with its picture. Place depth and section thickness from two or more
  views of the same feature — never trust a single camera for depth or cross-section.
- Read a width, height or depth from the view that sees it face-on. Edge-on, it is a guess.
- A bright streak on glass or paint is a reflection, not an edge. Take an edge under glare from another view.
- Press photos are sometimes not symmetric at the outer edges. Fit to the side that other views confirm.
- Say what you measured and what you fitted between the measurements.
- Every edge is a straight line, an arc or one smooth curve with few control points. Fit the curve to the
  measurements, then build the mesh on the curve. Strips keep one width. Corners are arcs or clean mitres.
- Each painted panel is one surface. A repair moves or replaces the old surface and joins edge to edge. Never
  share control points between a recessed cutout/intake and a continuous exterior shoulder sweep.
- HARD RULE — No visible ripples on the body: absolutely no ripples are allowed to be visible on the body of a
  vehicle. If any ripple appears, find the root cause and address it, note why it happened, and if there is a
  way to improve the skill to prevent it from happening again, propose that improvement in your report.
- Cut openings on a real edge loop in the surface, then measure how far the vertices sit from the curve.
  Carry every crease or opening cleanly into its adjacent painted return face.
- Visibility beats geometry count: a small detail (stitching, perforations, mesh, lamp optics, switch
  legends) counts only when it reads at native photographic scale in the installed vehicle, on both lit and
  shadowed sides.
- Moving or reshaping a part requires rechecking neighbouring sightlines (controls, gauges, adjacent panels),
  not just physical clearance.
- If two measurements cannot both hold, say which you kept, which you traded and by how much.
```

## Builder brief (a new assembly)

```
<Common rules>

Your assembly: <name>. It covers <list of parts>. It ends where <neighbour> begins: <the shared edge>.
Write src/<assembly>.py with build(ctx). Register every object with ctx.add (pass exterior=False for interior,
cabin, wheelhouse-liner, internal-brake, engine-bay and hidden-underbody objects), mark painted skin as a
panel, real creases with ctx.crease, any returned edge or inner face with ctx.inner, closed seating edges
with ctx.seat_edge (vertex group rg_seat), and take every material from ctx.material.
<Body assembly:> Publish each cut opening's ordered perimeter in mm with ctx.publish_interface(name, points)
so downstream assemblies seat to the real apertures.
<Downstream assemblies:> Read the accepted body's published openings with ctx.interface(name) as well as
ctx.body.hit / ctx.body.nearest.
<Level 2 or 3:> These parts come off and are listed in data/parts.json: <list>. Give each its own object,
registered separable with the pivot written there (ctx.part gives it), and thickness, a returned edge and an
inner face marked with ctx.inner.
<Dynamic parts even at Level 1:> Keep wheels, emissive lamp elements (separate slots for lit/unlit), gauge
needles/displays and door panes cleanly separable so downstream lighting or animation can drive them.

Assigned Feature Ledger items (prove each installed, at matching angle and scale):
<feature: reference file, key visual/depth/arrangement cues, chosen option/state, junction owner>

Assigned Small-Details Checklist items (do not defer):
<flaps, markers, cowl vents, badges, wipers, fasteners, trim details>

Before building each intricate feature, count its pieces AND record its arrangement, spacing, depth and
operating state from the close-up. Get the whole assembly present and in place first, then prove each
Feature Ledger item installed on the vehicle.

How you work:
- Blender in background mode only, one run at a time. Try your module with
  tools/assemble.py --working <assembly>, which builds out/work-<assembly>.blend. Make your own comparison
  pictures with tools/render_views.py --trial --view <name>, tools/compare.py and tools/details.py, and check
  a part that sits on a panel with tools/seating.py --part <name> --on <panel>.
- For every assigned Feature Ledger item, render a side-by-side comparison at the reference photo's angle and
  native scale:
  * glazed or transparent openings (bonnets, roofs, lamps, windows): include an offset/parallax view proving
    internal hardware sits and shifts at real depth behind the glass;
  * recessed intakes, ducts, vents and diffusers: include an oblique into-mouth view showing folded returns,
    mesh setback and through-opening sightlines;
  * layered lamps: compare in the chosen operating state (lit/unlit) and check optical density, spacing and
    order against the unlit reference too when available;
  * cabin and micro-details (leather grain, perforations, stitching, knurling, gauges, legends): render from
    the reference seat and driver's eye at native photo scale on both lit and shadowed sides, and check
    display/legend sightlines with details.py --sightlines.
- Stay inside your assembly. When a neighbour's part pokes through, falls short or blocks you, write it under
  "For another builder" with the size in mm.
- Read a neighbour's module only from accepted/.
- Write your report last, after every file it names exists.

Done when: assemble.py --working <assembly> runs clean; every part in your list and Small-Details Checklist
exists; parts that sit on the body are inside the seating limit (or the gap is reported in mm); and every
assigned Feature Ledger item has a verified installed reference comparison.

Report in notes/<assembly>/pass-00.md, with these headings:
<the pass report, pasted here>
```

## Judge brief (every round, a fresh judge)

```
<Common rules>

You are the judge for round <NN>. Judge the frozen candidate in evidence/round-<NN>/ against the references.
Leave the model and every other file as they are; you write only judge.md and marks.json in that folder.

You have: boards/ (each reference drawing and perspective photo beside a render from the same camera), lit/,
clay/, zebra/, orbit/ (all round and from above, in final paint and light), closeups/ (close views covering
the exterior), details/ (hero exterior, parallax, cabin and sightline views) and gates.json.
<extra evidence: for example the exploded view and the close-ups with each panel hidden>
You have not been told what the builders intended.
Not built yet, and not a fault this round: <assemblies still to come, or "nothing">.
Feature Ledger and Small-Details Checklist: data/plan.md.
Owner choices to protect narrowly (only the exact approved item/finish, not neighbouring surfaces): data/choices.md.

Look at every picture. For each orbit view, hero detail and close-up, open the reference pictures that show
the same part of the vehicle (refs/sources.json says what each one shows) and compare them side by side at
matching scale. Look along each edge, adjacent return face and multi-assembly join. Check:
- **Shape and section proportions:** measure key widths, gaps and cross-sections in native pixels across two
  angles where possible (not just outer silhouette).
- **Depth, arrangement and operating state:** verify part counts, grouping/order, overlap, recess depth and
  parallax behind glazing or lamp covers.
- **Material, optical and micro-detail realism:** call out flat/synthetic finishes, broad dark gutters in
  lamps, washed-out textures, invisible stitching/perforations in shadow, or occluded gauges and control
  legends at native photo density.
- **Small-Details Checklist:** audit every listed small feature (flaps, markers, vents, badges, wipers)
  separately so small misses are never starved by the top-15 list.
<extra instructions: for example "Parts marked reconstructed in data/parts.json are judged for being
plausible, complete and cleanly built, not for matching a photo.">

judge.md holds:
1. Faults, worst first, at most fifteen. For each: its number; the picture it shows in; what the reference
   shows; what the model shows; which assembly it belongs to (<the assemblies in the build list being judged>);
   BLOCKING (anyone would see it is wrong: any visible ripple on the body is an automatic BLOCKING fault; also
   a hole, a double skin, a part poking through, a wiggly edge, a wrong option/depth/arrangement, an occluded
   control/gauge, a missing opening, a cheap/flat finish or wrong proportion) or MINOR.
   Write each fault's place to marks.json, in the pixels of its picture, in the contract's format.
2. Small-Details Checklist audit: pass/open for every listed item.
3. A score out of 100 for each assembly, with one line on why. Scores are kept only to show the trend.
4. Which earlier faults and owner marks are gone and which remain. Earlier faults: <the previous round's
   judge.md, and the user-marks.md of the last stop; or "none">. A fault or owner mark is gone only when its
   original locked camera and box show it gone, and neighbouring views show no regression.
5. What you could not judge because no picture shows it.

Describe what you see in plain shapes. Leave the method of the fix to the builder.
```

## Fix note (manager to the builder of one assembly)

Write it as `notes/<assembly>/note-NN.md`. The picture is the judge's marked picture, or one you mark yourself
with `annotate.py`. On a board the mark sits on the render half and the note says where to look on the
reference half. On a ring close-up or detail render, name the reference file that shows the same place.

```
<Common rules, when the builder is new>

Area: <one area of your assembly>. Accepted and to be left exactly as it is (narrowly): <list>.

Picture: <marked picture>.
For each mark:
  <n>. The reference shows: <plain shapes, counts, arrangement, depth, where edges and adjacent faces run>.
       The model shows: <what differs>.
       Wanted: <the result, not the method>.

<If the fault looks like a symptom (ripple, bright patch, missing micro-detail):> First find the cause with a
controlled diagnostic (strip-light sweep / light toggle / A/B ON-OFF / denoise ON-OFF / rays.py --pixels) and
tell me what it is before changing shape. For any visible body ripple, record why it happened in your pass
report and propose a skill improvement if one would prevent it from happening again.

Measure before and after, in mm or native px (across the full marked span, not one point): <which quantity>.

Proof: reference, before and after side by side at matching scale in the exact original marked camera; a
second angle that exposes depth or section thickness; one neighbouring view capable of exposing a regression
(for cabin edits, include driver/passenger sightline checks to nearby controls); and
<rays.py --pixels at the join / seating.py round the part / fairness.py on the panel / details.py A/B toggle>.
Then write pass-NN.md with these headings and stop:
<the pass report, pasted here>

<If the builder stays running between notes:> Then wait for the next note with
tools/wait_for.py notes/<assembly>/note-<NN+1>.md and carry it out.

<If the last note was wrong:> My last note was wrong about <what>; this replaces it.
<If the area came from the owner:> The owner's words: "<quoted exactly>".
```

## Pass report (builder to manager)

`notes/<assembly>/pass-NN.md`, written last. Paste these headings into every builder brief and fix note:

```
What I built or changed in src/<assembly>.py.
For a fix: the cause I found (for any visible body ripple: why it happened, and any proposed skill improvement to prevent it recurring).
Parts and panels I registered, by name (noting exterior=False parts); published interfaces; and which parts sit on which panel.
Numbers: before and after for a fix; seating, dimensions and native-pixel measurements for a new assembly.
Proof pictures: <paths, including reference/before/after, depth/second-angle and regression views>.
What I measured and from which views; what I estimated.
What I traded, if anything.
For another builder: <part, what is wrong, mm>.
Noticed and not touched.
```

## Accepting a pass

`brief-00.md` is answered by `pass-00.md`, and each `note-NN.md` by the `pass-NN.md` of the same number.

Check the proof pictures and numbers yourself. To accept pass NN, run:

```
python tools/accept.py <assembly> <NN> --project <path> --depends-on <list> --seats <seats.json>
```

(`--also-build data/build-workshop.json` at level 3). It copies `src/<assembly>.py` to
`accepted/<assembly>/NN/`, writes its SHA-256 `manifest.json`, and updates every build list that names the
assembly. `assemble.py` builds only from `accepted/`, so work nobody accepted cannot reach the vehicle. To
return a pass, write the next note; no version is made for the one returned.
