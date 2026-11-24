# Working alone

Use this when you cannot start sub-agents. The steps, stops, gates and files in [SKILL.md](SKILL.md) stay the
same; you play each role in turn. Tell the user at Stop 2 that a solo build is slower and its judging is
weaker, because nobody else looks at the work before they do.

- **One assembly at a time.** Build in this order: body, front and rear ends, hardware, glass; then in Step 8
  cabin, underbody, what each removed panel uncovers (levels 2 and 3) and the mechanical assemblies (level 3).
  Assemble and render the whole vehicle after each.
- **Write the brief anyway.** Before each assembly write `notes/<assembly>/brief-00.md`, and before each fix
  the fix note, from [BRIEFS.md](BRIEFS.md); then carry it out. The note is what you check the result against.
- **Judge as a separate pass — strict 2-stage "Macro First".** Freeze the candidate and finish every render,
  `compare_zones.py`, `seams.py`, `daylight.py` and `gates.py` first. Then judge from the judge brief using
  only the pictures and `gates.json`: open no module and none of your own reports while judging. Look at the
  reference before the render, every time.
  - **Stage 1 first (5 images only):** Open ONLY `front`, `rear`, `left`, `front-left`, `rear-right` beside
    their references (plus `hero-zones.jpg`) before touching any cabin, wheel, decal or close-up render.
    Write `macro-triage.json` answering the 4 binary checks (lamp shapes/angles, zero daylight leaks, smooth
    continuous roofline/greenhouse, flush panel alignment). If ANY check fails, STOP before Stage 2, cap
    scores at `<= 55/100`, write `judge.md` with macro faults only, and fix macro geometry before doing any
    detail work.
  - **Stage 2 only after Stage 1 passes:** Inspect close-ups, cabin, wheels, decals and Small-Details Checklist.
    Write `judge.md` before anything else.
- **A fault you remember fixing is gone only when its own picture shows it gone.**
- **Lean on the user's stops.** Show more close-ups at Stops 3 and 4 than a team build would, and ask the
  user to mark what they see.
