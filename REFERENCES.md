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
| Close-ups of each intricate feature: lamps (lit and unlit where available) and their insides, grilles, intakes, vents, wheels, brakes, mirrors, wing, glazed covers, door handles, flaps, markers, badges | Builders read depth, spacing, arrangement and finish — not just part counts |
| Cabin photos, if the cabin is in scope: wide cockpit from passenger/driver side, steering wheel from two angles (showing rim thickness and stitching/texture), instrument cluster, seats and headrest junction, centre console/switchgear, open doorway/sill | Needed to judge cabin proportions, upholstery construction, control legibility and material tactility |
| Blueprints or dimensioned drawings of the exact variant | A drawing is solved as a flat camera and measured against like a photo. Watch for illustrative/dashed wheels or non-claimed parts in design patents |
| The maker's dimensions: length, width with and without mirrors, height, wheelbase, front and rear track, overhangs, tyre and wheel sizes, ground clearance | Scale, and the known points the cameras are solved from |
| For take-apart levels 2 and 3: cutaways, parts diagrams, workshop pictures | See TAKE-APART.md |

Where the maker never published a figure the tools need (a front overhang, say), scale it off a drawing of
the exact variant and list it under `estimated` in `vehicle.json`. If no drawing gives it either, leave it out
and tell the user at Stop 1.

For each file write one entry in `refs/sources.json`: where it came from, its licence, which view it is, whether
it is the exact variant, and **what it shows that no other file shows**.

## Audit divergent options and operating states

Different press, show and museum examples of the exact same variant frequently carry different factory options
or regional equipment (transparent vs. opaque engine/bonnet cover, lighting on vs. off, aero or roof position,
digital gauge modes, market-specific side markers, wheel or trim packages). List every visible divergence at
Stop 1 and lock the user's choice for each at Stop 2 before surface work begins. Never silently assume one
photo's option over another's.

## When the set is thin

An older or rarer vehicle may have no matched studio set. Then, in this order:

1. Use a drawing of the exact variant as a measured view: it solves to a flat camera and is graded like any
   photo. In `landmarks.json` a sheet with several views is one entry per view, each with its crop.
2. Use photos of different examples of the same variant, each solved on its own. Note in `sources.json` how
   each example differs (wheels, ride height, mirrors, options).
3. Say at Stop 1 which views are measured and which will be estimates, and what that means: a side with no
   precise view is built by eye and will be judged by eye.

## Solve the cameras

1. For each photo or drawing to be measured, find the pixel position of points whose place on the vehicle is
   known from the maker's dimensions. The contract's *Named points* table says exactly where each one sits
   (tyre contact, hub, the four ends of each rim, the extreme front, rear, sides and roof); add others to
   `vehicle.json` with their position. Write at least six per view, spread across the picture, to
   `data/landmarks.json`. On design-patent drawings where wheels or tyres are drawn in dashed lines as
   illustrative, do not use those tyre boxes as rigid camera landmarks — use body landmarks confirmed across
   elevations instead.
2. Always include **at least two perspective photographs** (front three-quarter and rear three-quarter, plus
   any key rear/front hero view) in `landmarks.json` alongside blueprints, even if they grade `visual`.
   Orthographic drawings alone cannot expose depth, recessed enclosures, lamp optics or panel waviness.
3. Front wheels are often turned in press photos. Where they are, leave out that view's front `rim_*` and
   `hub_*` points (turning moves both) and set `steer_deg` to 0 for now. It is set properly in Step 5, once
   there are wheels to render. Use `rim_*` points only when you know the diameter of the rim's visible edge;
   the nominal wheel size is smaller and would put every one of them out.
4. Run `solve_cameras.py`. It grades each view. A **precise** view is used for fitting and for the outline
   gate. A **visual** view is rendered into boards for side-by-side photographic comparison every round and
   not counted in the outline gate.
5. Make a silhouette mask for each precise view with `mask_photo.py` and look at its preview. For drawings
   with dashed boundaries, pass `--close-px <radius>` to bridge the dashes cleanly. If a drawing contains
   illustrative parts that disagree with factory dimensions (such as patent wheel boxes), you may also save an
   ignore mask (`refs/masks/<view>-ignore.png`, white = excluded) so `compare.py` measures the body outline
   cleanly without false errors. A mask that takes in a shadow or loses a dark tyre gives a wrong outline
   number in every round after. A view with a busy background waits for the first build: its mask is then
   seeded from a render through the same camera, and until it has one the view is compared by eye and left out
   of the outline gate.

The rules for reading a photo (face-on views, glare, symmetry, depth from two views) are in the common rules
in [BRIEFS.md](BRIEFS.md), because builders are the ones who apply them.
