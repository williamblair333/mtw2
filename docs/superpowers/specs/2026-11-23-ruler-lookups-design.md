# Ruler lookups: a short prompt, details on request

**Date:** 2026-11-23. **Decided by:** William ("2": rulers look things up when they need them).

## Why

France's prompt is ~136 KB a turn (turn 4448). Lossless trims (#696, #702, #704, #706) took off
~10 KB; the rest is real data: recruit lists 14 KB, public-order breakdowns 7.8 KB, unit prices
7 KB, buildings 4.6 KB, garrison troop lists, family 12 KB. A ruler reads all of it every turn,
though most turns it acts in a few towns. The outreach goal is a prompt under 60 KB.

The rule that stays: **rulers know everything** (memory `rulers-know-everything`). Nothing is
dropped; detail moves behind a lookup the ruler can always make.

## How it works

1. **Pass 1.** The ruler gets the short prompt. Each town line keeps what a ruler acts on every
   turn (place, garrison size, population, tax, public order %, rebel chance, income, queue,
   can build) and ends with `details: town:<id>`. Left out: the building list, the public-order
   breakdown, the recruit list, retrain, agents it can train, the unit price table, and the
   garrison's troop list. A `LOOKUPS` block says what a lookup returns.
2. The ruler answers as now (orders, note, plan), or with `"lookup": ["town:Arhus", ...]`
   and no orders.
3. **Pass 2** (only when it asked): the same short prompt plus `DETAILS YOU ASKED FOR`, each
   town's full entry (exactly what today's prompt prints for it, its garrison troops, and the
   prices of every unit it can recruit), and "give your orders now; no more lookups".
4. One lookup round a turn. `town:all` returns every town (today's full section).

Pass 2's answer is the turn's orders. Orders from pass 1 that came with a lookup are dropped
(the ruler was told to send none). A failed pass 2 is a seat error, handled as today.

## Opt-in

`[seats.<faction>] lookups = true`, default off. France goes first (largest prompt). Seats
without it get today's prompt, byte for byte (tested). The orders schema gains one optional
`lookup` list for every seat; a seat without lookups that sends one has it ignored.

Measured on France's turn-4448 report: full prompt 120.2 KB, short 75.3 KB, one town's details
~2.4 KB, `town:all` 68.7 KB (live prompts add ~13 KB of notes, lessons and messages).

## Files

- `turn-N/<faction>/prompt.txt`: pass 1. `lookup.txt`: the details sent in pass 2 (only when
  asked). `answer.txt`: the final answer; `answer1.txt`: pass 1's answer when there was a pass 2.

## Time

Both passes share `seat_timeout`: pass 2 gets what pass 1 left (at least 60 s). Haiku's median
answer on tc is ~32 s.

## How we judge it (France, ~30 turns before and after)

- prompt bytes (pass 1, and pass 1 + lookup when asked)
- how often it looks up, and which towns
- refused orders per turn, especially recruits and builds (the validator still checks against
  the full report)
- seat errors and timeouts

If refusals rise or it never looks up and plays worse, turn it off and rethink.

## Family (added 11-23, #709)

The short family list keeps the leader, the heir, generals and princesses, and counts the rest;
`"family"` returns the full list. Agents of one kind on one spot now share a line for every seat
(lossless). France turn 4448: short prompt 75.3 → 69.5 KB; the family lookup is 12.2 KB.

## Later, not now

Field-army troops could move behind `army:<id>` the same way. Measure first.
