# Helping with Parley

Thanks for looking. Parley is a small project, and a little expert help goes a long way. Below
are the places where help matters most, then how to send it.

## Where help matters most

### 1. EOP and Medieval II internals (the biggest need)

Two game actions still need a mouse click, because we found no way to do them from Lua:

- **Casting a papal election vote.** When the election scroll opens, our script finds the Vote
  buttons in a screenshot and clicks them. That only works at one screen size.
- **Answering a family offer**: a marriage or adoption the game offers your faction, on a scroll
  with accept and decline. We think pressing the scroll's own parts with `execute()` could work,
  but we haven't seen a live offer's parts yet.

If you know an EOP call, a game function, or a way to press a scroll's button from Lua, that
would remove our last clicks. See `lua/parley_bridge.lua` (search for `papal_election_scroll`) and
`docs/eop-api-notes.md` for what we already know.

Smaller open questions:
- Which game message is event id 160? (We believe it is the "Princess Disgraced!" message after
  a refused marriage, but we haven't confirmed it from `descr_event_enums`.)
- A real fog of war: EOP tells us which tiles a faction has *ever* seen, not which it sees *now*.
  Our rulers use a fixed sight radius instead.
- Orders for merchants (acquire a resource) and priests (denounce).

We also sent EOP a small fix: [EOP-Labs/M2TWEOP-library PR #90](https://github.com/EOP-Labs/M2TWEOP-library/pull/90).

### 2. Prompts that make small models play well

Large models rule competently but cost money per turn. Small and local models make mistakes:
idle armies, wasted gold, forgotten plans. Help here means reading a ruler's turn (its report in,
its orders out) and changing the prompt or the rules until a cheaper model plays better. The
prompt lives in `parley/prompt.py`. `just seat-bench` replays one recorded turn to several models
so you can compare their answers.

### 3. Playing and reporting

Install it, play a campaign, and tell us what broke. The most useful report has:
- what you did and what you expected;
- the bridge log: `<game folder>/parley_turns/parley_bridge.log` (the last 50 lines are usually
  enough);
- your graphics chip and Proton version, since the game's setup depends on them.

### 4. Other machines

We test on Debian with Proton 10. Reports from other distributions, Steam Deck, or different
graphics chips help us write a better install guide.

## How to send help

- **Bugs and questions:** open an issue on GitHub.
- **Code:** open a pull request. Run `just test` first; it must pass. A change to the bridge
  (`lua/parley_bridge.lua`) needs a test in `tests/` that runs it against the fake game in
  `tests/lua/fake_game.lua`. If you could, also say how you checked it in the real game.
- Keep changes small: one fix per pull request.

## Ground rules

- **No secrets in the repo.** Tokens and keys go only in the untracked env file at the repo root.
- **A ruler may do anything a human player could do, and nothing a human couldn't.** Every order
  goes through the game's own rules: cost, movement, buildings, time. No free gold, no spawned
  armies, no stance written straight into the game.
- **Rulers get the facts and decide.** Give a ruler information instead of restrictions. Code may
  help a ruler (fill a gap, warn it, catch an order that can't work), but it must never cancel or
  override an order the game would accept, and the ruler is told what was done.
- Be kind. Everyone here is doing this for fun.
