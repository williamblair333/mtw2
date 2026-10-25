# Observer mode: an LLM plays a whole faction, you watch and advise

Status: approved in conversation 2026-10-24 ("let's do all that… make the control granular").

## Intent

Pick a faction, start a campaign as it, and watch an LLM play it from the first turn to the
last without touching anything. Optionally talk strategy with it in a private Discord thread as
its loyal adviser. It weighs your advice and may overrule you.

## Goals

- **The observed faction is the human's slot** in the campaign (the one picked at the start),
  because the game's AI never runs it. So everything it does on the map is the LLM's doing.
- **Granular control, per seat.** Each area of play is either the LLM's or the game's:

  | Area | LLM | Game |
  |---|---|---|
  | `diplomacy` | stance, gold, cede, messages | the game's AI diplomacy (AI factions only) |
  | `armies` | move, attack, siege, withdraw any army | the game's AI (AI factions); idle (human slot) |
  | `agents` | assassinate, spy, bribe, sabotage, move | the game's AI / idle |
  | `build` | queue buildings | governor auto-manage |
  | `recruit` | queue units | governor auto-manage |
  | `taxes` | set tax levels | governor auto-manage |

  Presets: `diplomat` (diplomacy only), `ruler` (the default and the old behaviour: diplomacy,
  armies, agents; it now also allows `move_army` and `attack`) and `full` (everything but
  recruiting, which EOP 3.3.1 can't list safely while units are inside a settlement). Or list the areas directly. (A `general` preset was
  dropped: `ruler` already includes army orders.) The prompt shows only the orders an area allows. The checker and the bridge both
  refuse orders outside the seat's areas.
- **Adviser:** a seat may name a Discord user as its adviser. There's a private thread
  "adviser ↔ ruler". The ruler is told the adviser is loyal and wants it to win. It weighs the
  advice, may disagree and says why, keeps the adviser secret, and may write to the adviser
  first. The adviser's words reach its turn prompt, not just chat.
- **Unattended to the end:** autoplay ends turns. Battles involving the human slot
  auto-resolve. AI offers to the human slot are answered by the LLM or declined.
- **Watchable:** the on-screen Parley window shows the observed ruler's plan and orders. The
  camera may follow its armies if EOP allows.

## Non-goals

- Fighting battles in real time. Every battle auto-resolves.
- A perfect player. An LLM commanding many armies by coordinates will be clumsy at first. The
  presets let a game hand areas back to the governor.

## Anti-goals

- Hidden cheating. No `createUnit`-style shortcuts: the LLM gets only what a player could do.
  (Old Scratch's rule, "if a player can do it so can he", applies to everyone.)
- A stalled game. Any popup that needs a human is a bug to fix, logged as `stuck?`.

## Decided calls (mine, adjustable)

- Config: `control = "diplomat" | "ruler" | "full"` or `control = ["diplomacy", "armies", …]` on a
  seat, plus `adviser = "<discord username>"`. The default stays `ruler`, so existing games are
  unchanged.
- `build`, `recruit` and `taxes` set to "game" on the human slot means the bridge turns on the
  settlement's auto-manage, if EOP exposes it. Otherwise those areas are idle, and the docs say
  so.
- The adviser's private thread uses the same store and caps as the other private threads. An
  adviser is not a player: other rulers never see it in the player list.

## Build order

1. Control areas: config, prompt filtering, checker and bridge refusal. (Python and Lua.)
2. Adviser thread and adviser-aware prompts.
3. EOP research: build, recruit, units, movement, tax, auto-manage, battle auto-resolve,
   popups, camera (`docs/eop-api-notes.md`).
4. Bigger report and new orders for the areas EOP supports.
5. Battle and popup handling for the human slot.
6. Overlay plan line and camera follow.
7. An observer soak game, then live tuning.
