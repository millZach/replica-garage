# References and cameras

## Fix the variant first

Write maker, model, generation, model years and trim into `data/vehicle.json` before collecting anything.
Check every photo and drawing against it. Facelifts and neighbouring generations share a name and differ in
lamps, bumpers, arches and width; a drawing of the wrong one is kept out of shape decisions and marked so in
`refs/sources.json`.

## What to find

Free sources only: the maker's press pages, museum and archive pages, encyclopedias with open licences,
owner's manuals and brochures the maker publishes. Record the licence of each. Material stays in `refs/` on
this machine as a guide; nothing from it goes into the model or anything published. If a file's licence is
unclear, list it at Stop 1 and let the user decide.

| Need | Why |
|---|---|
| Studio photos on a plain background: front, rear, side, front three-quarter high and low, rear three-quarter | The cameras are solved from these, and outlines are measured against them |
| The same vehicle in every studio photo: same variant, wheels and ride height | A mixed set solves to cameras that disagree |
| Close-ups of each intricate feature: lamps and their insides, grilles, vents, wheels, brakes, mirrors, wing, door handles, badges | Builders count parts and read depth from these |
| Cabin photos, if the cabin is in scope: dash, seats, door card, wheel, console | |
| Blueprints or dimensioned drawings of the exact variant | A drawing is solved as a flat camera and measured against like a photo |
| The maker's dimensions: length, width with and without mirrors, height, wheelbase, front and rear track, overhangs, tyre and wheel sizes, ground clearance | Scale, and the known points the cameras are solved from |
| For take-apart levels 2 and 3: cutaways, parts diagrams, workshop pictures | See TAKE-APART.md |

Where the maker never published a figure the tools need (a front overhang, say), scale it off a drawing of
the exact variant and list it under `estimated` in `vehicle.json`. If no drawing gives it either, leave it out
and tell the user at Stop 1.

For each file write one entry in `refs/sources.json`: where it came from, its licence, which view it is, whether
it is the exact variant, and **what it shows that no other file shows**.

## When the set is thin

An older or rarer vehicle may have no matched studio set. Then, in this order:

1. Use a drawing of the exact variant as a measured view: it solves to a flat camera and is graded like any
   photo. In `landmarks.json` a sheet with several views is one entry per view, each with its crop.
2. Use photos of different examples of the same variant, each solved on its own. Note in `sources.json` how
   each example differs (wheels, ride height, mirrors).
3. Say at Stop 1 which views are measured and which will be estimates, and what that means: a side with no
   precise view is built by eye and will be judged by eye.

## Solve the cameras

1. For each photo or drawing to be measured, find the pixel position of points whose place on the vehicle is
   known from the maker's dimensions. The contract's *Named points* table says exactly where each one sits
   (tyre contact, hub, the four ends of each rim, the extreme front, rear, sides and roof); add others to
   `vehicle.json` with their position. Write at least six per view, spread across the picture, to
   `data/landmarks.json`.
2. Front wheels are often turned in press photos. Where they are, leave out that view's front `rim_*` and
   `hub_*` points (turning moves both) and set `steer_deg` to 0 for now. It is set properly in Step 5, once there are wheels to render.
   Use `rim_*` points only when you know the diameter of the rim's visible edge; the nominal wheel size is
   smaller and would put every one of them out.
3. Run `solve_cameras.py`. It grades each view. A **precise** view is used for fitting and for the outline
   gate. A **visual** view is for looking only.
4. Make a silhouette mask for each precise view with `mask_photo.py` and look at its preview. A mask that
   takes in a shadow or loses a dark tyre gives a wrong outline number in every round after. A view with a
   busy background waits for the first build: its mask is then seeded from a render through the same camera,
   and until it has one the view is compared by eye and left out of the outline gate.

The rules for reading a photo (face-on views, glare, symmetry, depth from two views) are in the common rules
in [BRIEFS.md](BRIEFS.md), because builders are the ones who apply them.
