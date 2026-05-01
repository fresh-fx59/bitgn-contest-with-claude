# Design constraints for a household assistant

Before I let this idea become a "platform," I want to write down the constraints that make it worth building at all.

If I do not do this early, the project will drift toward the usual failure modes: too much scope, too much enchantment, too much surveillance posture, too much hidden complexity, and not enough usefulness on an ordinary Wednesday.

## 1. It has to reduce load, not create a new hobby

The assistant is not allowed to become another dependent system that needs constant tuning, prompting, babysitting, dashboard grooming, or ritual maintenance just to justify its existence.

If it saves time only after I spend three weekends integrating and curating everything, then it is a workshop project, not household infrastructure.

The test is simple:

- does it make this week lighter
- does it help on a tired day, not just on an ambitious day
- would Petra describe it as useful rather than "one more thing you are currently very interested in"

That last one is brutal but fair.

## 2. Local-first is the default, not the slogan

Family life contains too many things that should not casually become cloud training slurry or vendor residue.

School notes, kindergarten messages, household routines, health-adjacent patterns, private tensions, children's details, and all the soft context that makes a home function should stay local unless there is a very clear reason not to.

This does not mean some cloud component can never exist. It means the burden of proof runs in one direction:

- local by default
- export intentionally
- keep the sensitive raw material close to home
- never pretend "temporary upload" is the same thing as no exposure

The assistant should earn trust partly by where it does not send things.

## 3. Household consent beats technical possibility

Just because something can be sensed, transcribed, linked, summarized, or inferred does not mean it should be.

I do not want to build a family panopticon decorated as convenience.

That means no ambient capture just because it is available.
No auto-listening room fantasy.
No creepy memory model that quietly turns domestic life into permanent searchable evidence.

If the household system knows something sensitive, it should be because a person deliberately placed it there for a clear reason. The assistant should help with explicit notes, chosen reminders, visible schedules, and bounded summaries more than with passive extraction.

Useful beats magical.
Visible beats spooky.

## 4. It must preserve lane boundaries

One of the biggest temptations in any "assistant" system is to merge everything because merged context looks smart.

In practice, merged context is how you leak the wrong thing into the wrong lane.

My life is not one context. It is overlapping contexts with different trust rules:

- family and children
- Petra's work and bureau-adjacent requests
- my day job
- consulting clients
- startup experiments
- private health and personal notes
- hobby clutter that should not suddenly become strategic input

The assistant should be able to notice relationships across those lanes without flattening them into one big context soup. It should help me navigate boundaries, not erase them.

## 5. It has to be interruption-friendly

This system is being designed for a life made of fragments.

That means it has to work for:

- ten-minute resumptions
- half-finished notes
- postponed tasks
- "what was I doing here" moments
- week plans broken by illness, school surprises, or work fires

A lot of productivity tooling quietly assumes clean context and long focus blocks. That is not my life. The assistant has to help on broken terrain.

If it only shines when I am already organized and well-rested, it is ornamental.

## 6. Quiet competence matters more than personality

I do not need a chirpy sidekick.

Tone matters, but mainly in the negative sense: the assistant should not sound theatrical, manipulative, overeager, or weirdly proud of ordinary actions. It should not manufacture intimacy. It should not pressure me to engage with it like it is a pet, a coach, or a social app.

The ideal tone is calm, direct, and slightly boring in the best possible way.

When it helps, I should feel supported.
When it is absent, I should feel nothing.

That is a compliment.

## 7. It must explain itself when the stakes are real

Invisible automation is only pleasant while everything is low-risk.

As soon as the system is crossing a boundary, making a commitment, inferring intent from messy notes, or omitting something that could matter, I need it to be legible.

Not verbose. Legible.

I want to know:

- what it knows from source
- what it inferred
- where the uncertainty is
- why it chose this summary, draft, or reminder
- when it needs confirmation instead of pretending confidence

If I cannot inspect the reasoning in important cases, then trust will decay the first time it gets something subtly wrong.

## 8. Good enough beats universal

I need to keep remembering that the first useful version is probably narrow and unglamorous.

The goal is not "an assistant for all of life."
The goal is probably something more like:

- one weekly household synthesis that is actually worth reading
- one reliable place for active reminders and pending follow-ups
- one way to resume stalled work without rereading half my own history
- one careful split between family-safe and lab-only context

That is already a lot.

If I try to solve voice, omnichannel capture, generalized planning, family displays, agentic action, and productization all at once, I will build a shrine to scope instead of a useful system.

## 9. It should improve the real week, not the imagined future week

I am unusually vulnerable to elegant future systems.

I can always picture the integrated version: better routing, smarter memory, cleaner dashboards, structured entities, ambient surfaces, graceful summaries, all of it.

That future picture is not useless, but it is dangerous.

The real question is more grounded:

- what helps this week
- what helps when someone is sick
- what helps when Petra needs something fast
- what helps when work is noisy and I have twenty minutes
- what still works when I am too tired to appreciate the architecture

If a feature only pays off in the imaginary life where I have spare cognitive bandwidth and uninterrupted weekends, it belongs on the parking lot, not in the assistant core.

## 10. The assistant should make me more present, not more optimized

This is the hardest one to evaluate and probably the most important.

The system is succeeding if it helps me keep promises, protect attention, and stop leaking important obligations through fatigue.

It is failing if it turns my family into a logistics problem, my hobbies into productivity units, or my own body into a dashboard with guilt attached.

I want leverage, not colonization.

That is the line.

## Working definition

For now, the shortest honest definition I have is this:

The assistant is a local-first continuity system for a busy household and overloaded working life.

It should help me remember, resume, separate, and follow through.

It should not perform omniscience.
It should not flatten trust boundaries.
It should not demand to become the center of the house.

If it becomes calm infrastructure, it has a future.
If it becomes another clever appetite, it does not.
