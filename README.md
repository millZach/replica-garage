# replica-garage

An agent skill for building an exact real vehicle in Blender from photos, blueprints and the maker's
dimensions.

It is written for an AI coding agent that can read files and run Blender. The agent acts as a manager: it
finds the references, solves a camera for each photo, directs a small team of builder agents, runs a fresh
judge against the photos each round, and stops to ask you at four fixed points. An agent that cannot start
sub-agents can follow the same steps alone.

![A Porsche 911 GT3 RS built with this method](examples/gt3rs/front-three-quarter.jpg)

The car above is the build this skill was written from. See [the worked example](examples/gt3rs/README.md)
for more pictures, the film, and what it took.

## Vehicles built with it

The GT3 RS came before the skill. These builds have used it since. Where a vehicle appears more than once,
different models built it side by side as a comparison, each running the manager and every sub-agent.

| Vehicle | Built by | Where it got to |
|---|---|---|
| 2011 Lamborghini Aventador LP 700-4 | Astra 6.2, Max | Finished; the first build with the skill. Its note is in `vehicles/` |
| Anakin Skywalker's Eta-2 Actis-class Jedi interceptor | Astra 6.2, Max | Taken through to a film |
| | Gemini 4 Neon, xhigh | Taken through to a film |
| 1994 Toyota Supra Mk4 (JZA80) from *The Fast and the Furious* | Gemini 4 Neon, high | Finished, after 27 judged rounds |
| | Astra 6.2, xhigh | First build, in progress |
| | Opus 5.5, xhigh | First build, in progress |
| 2026 Tesla Roadster | Astra 6.2, xhigh | Finishing, after 22 judged rounds |
| Tesla Cybercab | Astra 6.2, xhigh | First build, in progress |
| Tesla Semi | Astra 6.2, xhigh | First build, in progress |

The Supra was also built without the skill, by Gemini 4 Neon and by Opus 5.5, as a baseline to compare
against.

## What you get

A finished model: shape, paint, glass, lamps and interior, built entirely from code, with every colour as a
switch. If you ask for it, the vehicle comes apart: panels and wheels, or a full teardown to the bare shell.

## What it costs

Be ready for days of agent time. The build this skill came from, a Porsche 911 GT3 RS, took:

| | Agent hours | Cost at API prices |
|---|---|---|
| First finished car | 41.6 | $592 |
| With the fixes that followed | 74.3 | $1,073 |

Those figures are for the builder agents only and leave out the manager's own usage and render time.

## How it works

1. **References.** The agent finds free photos, drawings and the maker's dimensions, and shows you the set.
2. **Cameras.** It solves where each photo was taken from, so every later comparison is a render through that
   photo's own camera, set beside the photo.
3. **Look card.** It asks you for colours, finishes, plates, and how far the vehicle should come apart.
4. **First build.** Builders each write one assembly as code, the manager assembles them into one vehicle,
   and you see the whole thing early.
5. **Judge loop.** A fresh judge marks faults on pictures. Builders fix one marked area each. This runs as a
   baseline and up to three fix rounds before each time you are shown the vehicle.
6. **Your eye.** You see the measured gates, what still fails, and the close-ups, and you sign off or mark
   more.

## Install

Copy or clone this folder into your agent's skills folder, then ask it to build a vehicle:

> Use replica-garage to build a 1974 Lamborghini Countach LP400.

You need Blender and Python 3.10 or newer. `tools/requirements.txt` lists the Python packages.

## Honest limits

- **It comes from one build.** The method and the gate limits were worked out on a single car. The builds
  above have tried them on other cars and a starfighter; the first truck is in progress, and bikes are untried.
- **The tools are young.** They pass their tests on small made-up scenes and have carried a few whole builds
  to the end, listed above. That is not many.
- **It measures; it does not trace.** The build it came from used hand-traced drawings as well. This skill
  works from blueprints and photos through solved cameras only, and that route is still being proven.
- **Reference material stays with you.** The agent finds it from free sources and keeps it on your machine.
  Nothing a maker published is included here, and you should not publish it either.
- **A real vehicle carries real badges.** What you may do with a model of someone else's design is for you to
  check.

## What is in here

| | |
|---|---|
| `SKILL.md` | The manager's steps |
| `BRIEFS.md` | What each builder and judge is told, and the fix note format |
| `BLENDER.md` | Best practice for modelling, paint, light and rendering |
| `vehicles/` | Short notes on specific vehicles already built; add yours |
| `REFERENCES.md` | Finding references and solving cameras |
| `TAKE-APART.md` | The three take-apart levels |
| `SOLO.md` | Following the skill without sub-agents |
| `tools/` | Camera solving, comparison boards, close-ups, gates and the rest; see `tools/CONTRACT.md` |

## Licence

MIT. See [LICENSE](LICENSE).
