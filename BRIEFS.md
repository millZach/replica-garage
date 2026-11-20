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

How shape is decided:
- Measure against the precise views in data/cameras.json: render through a view's camera and compare with its
  picture. Place depth from two or more views of the same feature.
- Read a width, height or depth from the view that sees it face-on. Edge-on, it is a guess.
- A bright streak on glass or paint is a reflection, not an edge. Take an edge under glare from another view.
- Press photos are sometimes not symmetric at the outer edges. Fit to the side that other views confirm.
- Say what you measured and what you fitted between the measurements.
- Every edge is a straight line, an arc or one smooth curve with few control points. Fit the curve to the
  measurements, then build the mesh on the curve. Strips keep one width. Corners are arcs or clean mitres.
- Each painted panel is one surface. A repair moves or replaces the old surface and joins edge to edge.
- Cut openings on a real edge loop in the surface, then measure how far the vertices sit from the curve.
- If two measurements cannot both hold, say which you kept, which you traded and by how much.
```

## Builder brief (a new assembly)

```
<Common rules>

Your assembly: <name>. It covers <list of parts>. It ends where <neighbour> begins: <the shared edge>.
Write src/<assembly>.py with build(ctx). Register every object with ctx.add, mark painted skin as a panel,
real creases with ctx.crease and any returned edge or inner face with ctx.inner, and take every material from
ctx.material.
<Level 2 or 3:> These parts come off and are listed in data/parts.json: <list>. Give each its own object,
registered separable with the pivot written there (ctx.part gives it), and thickness, a returned edge and an
inner face marked with ctx.inner.

Best reference close-ups for the intricate parts: <feature: file>. Before building each, count its pieces in
the close-up and write down what you counted.

Get the whole assembly present and in place first, then add detail.

How you work:
- Blender in background mode only, one run at a time. Try your module with
  tools/assemble.py --working <assembly>, which builds out/work-<assembly>.blend. Make your own comparison
  pictures with tools/render_views.py --trial --view <name> and tools/compare.py, and check a part that sits
  on a panel with tools/seating.py --part <name> --on <panel>.
- Stay inside your assembly. When a neighbour's part pokes through, falls short or blocks you, write it under
  "For another builder" with the size in mm.
- Read a neighbour's module only from accepted/.
- Write your report last, after every file it names exists.

Done when: assemble.py --working <assembly> runs clean; every part in your list exists; parts that sit on the
body are inside the seating limit, or the gap is reported in mm.

Report in notes/<assembly>/pass-00.md, with these headings:
<the pass report, pasted here>
```

## Judge brief (every round, a fresh judge)

```
<Common rules>

You are the judge for round <NN>. Judge the frozen candidate in evidence/round-<NN>/ against the references.
Leave the model and every other file as they are; you write only judge.md and marks.json in that folder.

You have: boards/ (each reference picture beside a render from the same camera), lit/, clay/, zebra/,
orbit/ (the vehicle from all round and from above, in its final paint and light), closeups/ (close views
covering the whole vehicle) and gates.json.
<extra evidence: for example the exploded view and the close-ups with each panel hidden>
You have not been told what the builders intended.
Not built yet, and not a fault this round: <assemblies still to come, or "nothing">.

Look at every picture. For each orbit view and each close-up, open the reference pictures that show the same
part of the vehicle (refs/sources.json says what each one shows) and compare them side by side. Look along
each edge and each join. Compare part counts with the reference close-ups. Call out what a person would see
is different: shape, proportion, a missing or extra part, a wrong count, a finish that reads wrongly.
<extra instructions: for example "Parts marked reconstructed in data/parts.json are judged for being
plausible, complete and cleanly built, not for matching a photo.">

judge.md holds:
1. Faults, worst first, at most fifteen. For each: its number; the picture it shows in; what the reference
   shows; what the model shows; which assembly it belongs to (<the assemblies in the build list being judged>); BLOCKING (anyone would see it is wrong: a hole, a double skin, a part poking through, a
   wiggly edge, a wrong count, a wrong proportion) or MINOR.
   Write each fault's place to marks.json, in the pixels of its picture, in the contract's format.
2. A score out of 100 for each assembly, with one line on why. Scores are kept only to show the trend.
3. Which earlier faults are gone and which remain. Earlier faults: <the previous round's judge.md, and the
   user-marks.md of the last stop; or "none">. A fault is gone only when its own picture shows it gone.
4. What you could not judge because no picture shows it.

Describe what you see in plain shapes. Leave the method of the fix to the builder.
```

## Fix note (manager to the builder of one assembly)

Write it as `notes/<assembly>/note-NN.md`. The picture is the judge's marked picture, or one you mark yourself
with `annotate.py`. On a board the mark sits on the render half and the note says where to look on the
reference half. On a ring close-up, name the reference file that shows the same place.

```
<Common rules, when the builder is new>

Area: <one area of your assembly>. Accepted and to be left exactly as it is: <list>.

Picture: <marked picture>.
For each mark:
  <n>. The reference shows: <plain shapes, counts, where edges run>.
       The model shows: <what differs>.
       Wanted: <the result, not the method>.

<If the fault looks like a symptom:> First find the cause and tell me what it is before changing shape.

Measure before and after, in mm or px: <which quantity>.

Proof: the same picture and layout, before beside after; one view from a side this note does not name; and
<rays.py --pixels at the join / seating.py round the part / fairness.py on the panel>. Then write pass-NN.md
with these headings and stop:
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
For a fix: the cause I found.
Parts and panels I registered, by name; and which parts sit on which panel.
Numbers: before and after for a fix; seating and dimensions for a new assembly.
Proof pictures: <paths>.
What I measured and from which views; what I estimated.
What I traded, if anything.
For another builder: <part, what is wrong, mm>.
Noticed and not touched.
```

## Accepting a pass

`brief-00.md` is answered by `pass-00.md`, and each `note-NN.md` by the `pass-NN.md` of the same number.

Check the proof pictures and numbers yourself. To accept pass NN, copy `src/<assembly>.py` to
`accepted/<assembly>/NN/`, write its `manifest.json` (assembly, version, the file's SHA-256 and what it
depends on, as the contract lays out) and set that version in every build list that names the assembly. `assemble.py` builds only from there, so work nobody accepted cannot reach
the vehicle. To return a pass, write the next note; no version is made for the one returned.
