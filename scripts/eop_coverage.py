#!/usr/bin/env python3
"""EOP scripting coverage: what EOP's Lua API exposes, and what our bridge uses.

Usage:
    python scripts/eop_coverage.py [--eop DIR] [--bridge FILE ...] [--md OUT.md] [--json OUT.json]

Stdlib only. Everything here is a heuristic over text, not a C++ or Lua parser.

EOP side (the sol2 bindings in `M2TWEOP library/types/*.cpp`, `luaPlugin.cpp`,
`luaLegacy.cpp`, `luaEnums.cpp`):
  * `X = luaState.new_usertype<T>("name")` binds a C++ receiver variable to a Lua type name.
    Receivers `tables.M2TWEOP`, `tables.game`... are Lua tables, named in TABLE_NAMES.
  * `X.set("member", ...)` is a field or property; `X.set_function("member", ...)` a function.
    `sol::property(get)` (one argument) is read-only, `sol::property(get, set)` writable,
    `sol::readonly(...)` read-only, a bare `&Struct::field` writable. A `set` whose doc says
    `@function`, or whose `@tfield` type repeats its own name, is a function.
  * Descriptions come from the `/*** ... */` EmmyLua/LDoc blocks: a block that ends right before
    a binding documents it (`@function Type:name`); the header block of a type lists
    `@tfield type name description` for its fields (matched through `@table Type`).
  * Events are the `@function onXxx` doc blocks in `types/events.cpp` (description plus the
    `Exports:` line, which names the event's data fields).
  * `luaState.new_enum("name", "a", V, ...)` gives enum members (kind `enum`).

Our side (`lua/parley_bridge.lua`, `lua/luaPluginScript.lua`): comments and string contents are
blanked, then a member counts as USED when `.member` or `:member` appears. The Lua file is split
into top-level functions; a call graph (a name appearing in another body) says which roots reach
each function: `M.report` is the report, `handlers.*` are orders, `M.on_*` are events, anything
else is `other` (UI, control, helpers nothing above reaches). Report keys (REPORT_KEYS) name the
StateReport field a helper feeds. Limits:
  * Matching is by member name only. A name that several types declare (`name`, `x`, `faction`)
    is flagged ambiguous (`?`): the bridge may use another type's member of that name.
  * A member read through a dynamic string (`obj[key]`) is not seen.
  * Reaching the report means the code path runs for the report, not that every value is rendered
    in the prompt; parley/prompt.py decides that.

Relevance tags: campaign (a ruler could use it), battle, ui, modding (files, models, textures,
settings, internals), unknown. Set per type (TYPE_RULES) with per-member overrides (MEMBER_RULES).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EOP = "../M2TWEOP-library"
LIB = "M2TWEOP Code/M2TWEOP library"
BRIDGES = ["lua/parley_bridge.lua", "lua/luaPluginScript.lua"]

# C++ receiver -> the Lua name of the table it fills
TABLE_NAMES = {
    "tables.M2TWEOP": "M2TWEOP",
    "tables.game": "stratmap.game",
    "tables.camera": "stratmap.camera",
    "tables.objects": "stratmap.objects",
    "tables.stratmap": "stratmap",
    "tables.gameUITable": "gameSTDUI",
    "tables.M2TWEOPEDUTable": "M2TWEOPDU",
}

# --------------------------------------------------------------------------------------
# domains: usertype -> (domain, default relevance). Order of DOMAINS is the report order.
# --------------------------------------------------------------------------------------
DOMAINS = [
    ("Faction", "campaign"),
    ("Character and character record", "campaign"),
    ("Settlement", "campaign"),
    ("Army and unit", "campaign"),
    ("Strategy map, tiles and regions", "campaign"),
    ("Campaign, diplomacy and game state", "campaign"),
    ("Religion, papacy and crusades", "campaign"),
    ("Buildings and recruitment", "campaign"),
    ("Campaign AI", "campaign"),
    ("Fort, port, watchtower and resources", "campaign"),
    ("Events", "campaign"),
    ("Global functions (M2TWEOP, stratmap)", "campaign"),
    ("Enums and constants", "unknown"),
    ("Battle", "battle"),
    ("UI", "ui"),
    ("Campaign rules database (tunables)", "modding"),
    ("Modding and internals", "modding"),
]

TYPE_DOMAIN = {
    # faction
    "factionStruct": "Faction", "factionRecord": "Faction", "factionEconomy": "Faction",
    "factionRanking": "Faction", "battleFactionCounter": "Faction", "holdRegionsWinCondition": "Faction",
    "rebelFactionStruct": "Faction", "rebelFaction": "Faction", "eopFactionData": "Faction",
    # character
    "character": "Character and character record", "characterRecord": "Character and character record",
    "traitContainer": "Character and character record", "traitEntry": "Character and character record",
    "ancillary": "Character and character record", "ancillaryContainer": "Character and character record",
    "namedCharacter": "Character and character record", "familyTreeEntry": "Character and character record",
    "characterMovementExtents": "Character and character record", "movementExtentTile": "Character and character record",
    "characterMoveData": "Character and character record", "moveDataSettlement": "Character and character record",
    "moveDataCharacter": "Character and character record", "moveDataArmy": "Character and character record",
    "moveDataResource": "Character and character record", "moveDataFort": "Character and character record",
    "moveDataTile": "Character and character record", "ancillaryStruct": "Character and character record",
    "trait": "Character and character record", "traitLevel": "Character and character record",
    "characterRecordSkills": "Character and character record",
    # settlement
    "settlementStruct": "Settlement", "settlementStats": "Settlement", "settlementCapability": "Settlement",
    "settlementRecruitmentPool": "Settlement", "settlementRecruitmentPoolItem": "Settlement",
    "siegeStruct": "Settlement", "siegeEquipmentQueueItem": "Settlement",
    "settlementTexture": "Modding and internals",
    # army / unit
    "armyStruct": "Army and unit", "unit": "Army and unit", "unitGroup": "Army and unit",
    "unitPositionData": "Army and unit", "attackStats": "Army and unit", "unitTrainingQueue": "Army and unit",
    "mercPool": "Army and unit", "mercPoolUnit": "Army and unit", "eduEntry": "Army and unit",
    "M2TWEOPDU": "Army and unit", "unitRQ": "Army and unit", "unitStats": "Army and unit",
    "unitInfo": "Army and unit", "recruitmentQueueItem": "Army and unit",
    # map
    "stratMap": "Strategy map, tiles and regions", "tileStruct": "Strategy map, tiles and regions",
    "regionStruct": "Strategy map, tiles and regions", "roadStruct": "Strategy map, tiles and regions",
    "seaConnectedRegion": "Strategy map, tiles and regions", "landMass": "Strategy map, tiles and regions",
    "regionData": "Strategy map, tiles and regions", "mapImage": "Modding and internals",
    "weatherData": "Strategy map, tiles and regions", "neighbourRegion": "Strategy map, tiles and regions",
    # campaign
    "campaignStruct": "Campaign, diplomacy and game state", "factionDiplomacy": "Campaign, diplomacy and game state",
    "gameDataAll": "Campaign, diplomacy and game state", "campaignDifficulty1": "Campaign, diplomacy and game state",
    "campaignDifficulty2": "Campaign, diplomacy and game state", "selectionInfo": "Campaign, diplomacy and game state",
    "eventTrigger": "Events", "campaignEvents": "Events",
    # religion
    "collegeOfCardinals": "Religion, papacy and crusades", "cardinal": "Religion, papacy and crusades",
    "crusadeStruct": "Religion, papacy and crusades", "jihadStruct": "Religion, papacy and crusades",
    "crusadeReward": "Religion, papacy and crusades", "religionStruct": "Religion, papacy and crusades",
    # buildings
    "buildingInQueue": "Buildings and recruitment", "buildingStruct": "Buildings and recruitment",
    "building": "Buildings and recruitment", "buildingLevel": "Buildings and recruitment",
    "EDB": "Buildings and recruitment", "buildingsQueue": "Buildings and recruitment",
    "buildingCapability": "Buildings and recruitment", "recruitPool": "Buildings and recruitment",
    "recruitCapability": "Buildings and recruitment", "buildingPlugin": "Buildings and recruitment",
    "eopBuildings": "Buildings and recruitment", "eopProductionHelper": "Buildings and recruitment",
    # AI
    "aiFaction": "Campaign AI", "aiLongTermGoalDirector": "Campaign AI", "aiPersonality": "Campaign AI",
    "aiGlobalStrategyDirector": "Campaign AI", "decisionValuesLTGD": "Campaign AI", "aiFactionValues": "Campaign AI",
    "interFactionLTGD": "Campaign AI", "aiFactionData": "Campaign AI", "eopAiConfig": "Campaign AI",
    "aiProductionController": "Campaign AI", "aiRegionData": "Campaign AI", "aiResourceManager": "Campaign AI",
    # fort etc
    "fortStruct": "Fort, port, watchtower and resources", "watchtowerStruct": "Fort, port, watchtower and resources",
    "portStruct": "Fort, port, watchtower and resources", "dockStruct": "Fort, port, watchtower and resources",
    "tradeResource": "Fort, port, watchtower and resources",
    # globals
    "M2TWEOP": "Global functions (M2TWEOP, stratmap)", "stratmap": "Global functions (M2TWEOP, stratmap)",
    "stratmap.game": "Global functions (M2TWEOP, stratmap)", "stratmap.camera": "Global functions (M2TWEOP, stratmap)",
    "stratmap.objects": "Global functions (M2TWEOP, stratmap)", "gameSTDUI": "UI",
    "M2TW": "Global functions (M2TWEOP, stratmap)",
    "capturedCharacter": "Character and character record", "capturedUnit": "Army and unit",
    "capturedFactionInfo": "Character and character record",
    "rebelCategory": "Faction", "rebelUnit": "Faction", "eopRebelFaction": "Faction",
    "guild": "Campaign, diplomacy and game state", "missionDetailsStruct": "Campaign, diplomacy and game state",
    "siegeEngineStruct": "Settlement", "minorSettlementBalance": "Settlement",
    "settlementTextStrings": "UI", "settlementInfoScroll": "UI", "unitInfoScroll": "UI",
    "buildingInfoScroll": "UI", "options1": "UI", "options2": "UI",
    "constructionOptions": "Buildings and recruitment", "capability": "Buildings and recruitment",
    "edbEntry": "Buildings and recruitment", "recruitmentOptions": "Buildings and recruitment",
    "recruitmentCapability": "Buildings and recruitment", "unitInQueue": "Army and unit",
    "landingPoint": "Strategy map, tiles and regions", "landingTile": "Strategy map, tiles and regions",
    "stratMovePath": "Strategy map, tiles and regions", "coordPair": "Strategy map, tiles and regions",
    "defenseStats": "Battle", "projectileStruct": "Battle", "generalBattleStruct": "Battle",
    "mountStruct": "Modding and internals", "vector3": "Modding and internals",
    "mapImageStruct": "Modding and internals",
}

# types that match no explicit entry are filed by these name patterns, first match wins
TYPE_PATTERNS = [
    (r"^battle|^deployment|^terrain|^perimeter|^street|^plaza|^phalanx|^lineData|^tower|^buildingBattle|"
     r"^fortBattle|^battlefield|^battleSide|Battle", "Battle"),
    (r"^ui|UI|^imgui|^button|^scroll|^screen|^gui|^font|^menu|^element|^panel|^text|^dialog|^camera", "UI"),
    (r"^ai|AI", "Campaign AI"),
    (r"^campaignDb", "Campaign rules database (tunables)"),
    (r"^settlement|^siege", "Settlement"),
    (r"^faction|^rebel", "Faction"),
    (r"^army|^unit|^edu|^merc", "Army and unit"),
    (r"^character|^trait|^ancillary|^moveData", "Character and character record"),
    (r"^region|^tile|^stratMap|^road", "Strategy map, tiles and regions"),
    (r"^building|^EDB|^recruit", "Buildings and recruitment"),
    (r"^fort|^port|^watch|^dock|^resource|^trade", "Fort, port, watchtower and resources"),
    (r"^crusade|^jihad|^cardinal|^college|^relig|^pope", "Religion, papacy and crusades"),
]

# Member-level overrides inside campaign domains: a member whose camelCase words include one of
# these is filed as modding/internal (files, models, textures, settings) or as UI.
MODDING_WORDS = set("""path folder file model texture fbx dds shader mesh cas sprite icon bmp tga skin sound music
voice font draw render color colour banner logo loading hook offset dll plugin console debug developer config
setting settings lua script scripts hash pointer address memory""".split())
UI_WORDS = set("screen panel button scroll click selected camera zoom tooltip popup window imgui gui ui".split())

KIND_FIELD, KIND_PROP, KIND_FUNC, KIND_ENUM, KIND_EVENT = "field", "property", "function", "enum", "event"

PRIMS = {"int", "float", "bool", "string", "number", "table", "void", "nil", "char", "boolean", "long", "double"}


@dataclass
class Member:
    owner: str  # usertype or table name
    name: str
    kind: str
    access: str  # "ro", "rw", "" (functions, unknown)
    desc: str
    file: str
    line: int
    type: str = ""  # from @tfield, when documented
    domain: str = ""
    relevance: str = ""
    used_in: set = field(default_factory=set)  # roles: report, order, event, other
    report_keys: set = field(default_factory=set)
    ambiguous: bool = False

    @property
    def used(self) -> bool:
        return bool(self.used_in)


# --------------------------------------------------------------------------------------
# EOP parsing
# --------------------------------------------------------------------------------------
DOC_RE = re.compile(r"/\*\*\*(.*?)\*/", re.S)
DECL_RE = re.compile(r"([\w.]+)\s*=\s*(?:[\w:]+\.)*new_usertype<[^>]*>\(\s*\"(\w+)\"")
TABLE_DECL_RE = re.compile(r"(tables\.\w+)\s*=\s*luaState\.create_table")
BIND_RE = re.compile(r"([\w.]+)\.(set_function|set)\s*\(")
ENUM_RE = re.compile(r"new_enum(?:<[^>]*>)?\(\s*\"(\w+)\"")


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def balanced(text: str, start: int) -> int:
    """Index just past the ')' matching the '(' at text[start]; strings are skipped."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def split_args(s: str) -> list[str]:
    """Split a call's argument text at top-level commas."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(s):
        c = s[i]
        if c == '"':
            j = i + 1
            while j < len(s) and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i : j + 1])
            i = j + 1
            continue
        if c in "(<[{":
            depth += 1
        elif c in ")>]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur).strip())
    return out


def clean_doc(block: str) -> list[str]:
    lines = []
    for ln in block.splitlines():
        ln = ln.strip()
        lines.append(ln)
    return lines


def doc_description(lines: list[str]) -> str:
    """The prose before the first @tag, joined on spaces."""
    out = []
    for ln in lines:
        if ln.startswith("@"):
            break
        if ln:
            out.append(ln)
    return " ".join(out)


def doc_tags(lines: list[str], tag: str) -> list[str]:
    return [ln[len(tag) + 1 :].strip() for ln in lines if ln.startswith(tag + " ") or ln == tag]


METHOD_DEF_RE = re.compile(r"\b(\w+::\w+)\s*\(")


def classify_binding(kind_call: str, args: list[str], doc_func: bool, methods: set[str], desc: str):
    """(kind, access) from a set/set_function call, its doc, and the C++ method definitions seen."""
    if kind_call == "set_function" or doc_func:
        return KIND_FUNC, ""
    target = args[1] if len(args) > 1 else ""
    if target.startswith(("sol::overload", "sol::factories", "sol::resolve")):
        return KIND_FUNC, ""
    if target.startswith("sol::property"):
        inner = target[target.index("(") + 1 : target.rindex(")")]
        parts = [p for p in split_args(inner) if p]
        return KIND_PROP, ("rw" if len(parts) >= 2 else "ro")
    ro = bool(re.search(r"(?i)\b(get|read)[ -]only\b", desc))
    if target.startswith("sol::readonly"):
        return KIND_FIELD, "ro"
    if target.startswith("&"):
        sym = target[1:].strip()
        # a method (defined in a .cpp), a free function, or a namespace function (xxxHelpers::)
        if sym in methods or "::" not in sym or sym.split("::")[0].endswith("Helpers"):
            return KIND_FUNC, ""
        return KIND_FIELD, "ro" if ro else "rw"
    return KIND_FIELD, ""


def parse_cpp(text: str, relfile: str, methods: set[str] = frozenset()) -> tuple[list[Member], list[Member], list[str]]:
    """Members bound in one file, enum members, and the list of usertype names declared."""
    recv: dict[str, str] = {}
    for m in DECL_RE.finditer(text):
        recv[m.group(1)] = m.group(2)
    for r, n in TABLE_NAMES.items():
        recv.setdefault(r, n)

    # doc blocks: position, end, lines
    docs = [(m.start(), m.end(), clean_doc(m.group(1))) for m in DOC_RE.finditer(text)]

    # field docs from header blocks: owner -> {name: (type, desc)}
    tfields: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    type_desc: dict[str, str] = {}
    decl_pos = [(m.start(), m.group(2)) for m in DECL_RE.finditer(text)]
    for start, end, lines in docs:
        owner = None
        for t in doc_tags(lines, "@table"):
            owner = t.split()[0]
        if owner is None:  # a header block with no @table belongs to the usertype declared right after
            after = [n for p, n in decl_pos if p >= end and p - end < 80]
            owner = after[0] if after else None
        for tf in doc_tags(lines, "@tfield"):
            parts = tf.split(None, 2)
            if len(parts) >= 2 and owner:
                tfields[owner][parts[1]] = (parts[0], parts[2] if len(parts) > 2 else "")
        if owner and any(ln.startswith("@tfield") for ln in lines):
            type_desc[owner] = doc_description(lines)

    members: list[Member] = []
    seen: set[tuple[str, str]] = set()
    for m in BIND_RE.finditer(text):
        r = m.group(1)
        if r not in recv:
            continue
        owner = recv[r]
        open_i = m.end() - 1
        end_i = balanced(text, open_i)
        args = split_args(text[open_i + 1 : end_i - 1])
        if not args or not args[0].startswith('"'):
            continue
        name = args[0].strip('"')
        if (owner, name) in seen:
            continue
        seen.add((owner, name))
        # the doc block that ends right before this binding (only whitespace / // lines between)
        doc = None
        for ds, de, lines in docs:
            if de <= m.start() and re.fullmatch(r"(\s|//[^\n]*)*", text[de : m.start()]):
                doc = lines
        doc_func = bool(doc) and any(ln.startswith("@function") for ln in doc)
        desc = doc_description(doc) if doc and doc_func else ""
        tftype, tfdesc = tfields.get(owner, {}).get(name, ("", ""))
        if not desc:
            desc = tfdesc
        kind, access = classify_binding(m.group(2), args, doc_func, methods, desc)
        members.append(Member(owner, name, kind, access, desc.strip(), relfile, line_of(text, m.start()), tftype))

    # enums
    enums: list[Member] = []
    for m in ENUM_RE.finditer(text):
        ename = m.group(1)
        end_i = balanced(text, text.index("(", m.start()))
        args = split_args(text[text.index("(", m.start()) + 1 : end_i - 1])[1:]
        names = [a.strip('"') for a in args[0::2] if a.startswith('"')]
        for n in names:
            tftype, tfdesc = tfields.get(ename, {}).get(n, ("int", ""))
            enums.append(Member(ename, n, KIND_ENUM, "ro", tfdesc, relfile, line_of(text, m.start()), tftype))
        type_desc.setdefault(ename, "")
    return members, enums, [n for _, n in decl_pos]


def parse_events(text: str, relfile: str) -> list[Member]:
    """`@function onXxx` blocks: description, and the Exports: line."""
    out = []
    for m in DOC_RE.finditer(text):
        lines = clean_doc(m.group(1))
        funcs = [f for f in doc_tags(lines, "@function") if re.fullmatch(r"on\w+", f)]
        if not funcs:
            continue
        prose = []
        for ln in lines:  # the prose ends at the first @tag; what follows @usage is example code
            if ln.startswith("@"):
                break
            if ln:
                prose.append(ln)
        desc = " ".join(ln for ln in prose if not ln.startswith("Exports:"))
        exports = next((ln for ln in prose if ln.startswith("Exports:")), "")
        text_desc = (desc + (" [" + exports + "]" if exports else "")).strip()
        out.append(Member("events", funcs[0], KIND_EVENT, "", text_desc, relfile, line_of(text, m.start())))
    return out


def eop_version(eop: Path) -> str:
    try:
        d = subprocess.run(["git", "-C", str(eop), "describe", "--tags", "--always"], capture_output=True,
                           text=True, timeout=20).stdout.strip()
        c = subprocess.run(["git", "-C", str(eop), "log", "-1", "--format=%cs"], capture_output=True,
                           text=True, timeout=20).stdout.strip()
        return f"{d} ({c})" if d else "unknown"
    except Exception:
        return "unknown"


def load_eop(eop: Path):
    lib = eop / LIB
    files = sorted((lib / "types").glob("*.cpp")) + [lib / "luaPlugin.cpp", lib / "luaLegacy.cpp", lib / "luaEnums.cpp"]
    methods: set[str] = set()  # "Struct::method" for every definition or call-looking name in the C++
    for f in list(lib.rglob("*.cpp")) + list(lib.rglob("*.h")):
        methods |= set(METHOD_DEF_RE.findall(f.read_text(errors="replace")))
    members, enums = [], []
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(errors="replace")
        rel = str(f.relative_to(eop / LIB))
        ms, es, _ = parse_cpp(text, rel, methods)
        members += ms
        enums += es
    ev_file = lib / "types" / "events.cpp"
    events = parse_events(ev_file.read_text(errors="replace"), "types/events.cpp") if ev_file.exists() else []
    return members, enums, events


# --------------------------------------------------------------------------------------
# domain and relevance
# --------------------------------------------------------------------------------------
def domain_of(owner: str) -> str:
    if owner in TYPE_DOMAIN:
        return TYPE_DOMAIN[owner]
    if owner == "events":
        return "Events"
    for pat, dom in TYPE_PATTERNS:
        if re.search(pat, owner):
            return dom
    return "Modding and internals"


def words_of(name: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)}


ENUM_CAMPAIGN = {"dipRelType", "characterType", "deathType", "resourceType", "buildingCapability", "characterAttr",
                 "unitCategory", "unitClass", "constructionType", "managePolicy", "productionBias",
                 "tileVisibility", "aiObjective", "aiPlan", "strategyGroundType", "unitStatus", "unitCategoryClass"}
ENUM_UI = {"cursorState", "searchType", "sortType"}
EVENT_UI = re.compile(r"Ui|UI|Scroll|Button|Shortcut|Advice|Loading|Menu|Click|Draw|Panel|Popup|Message|"
                      r"Frame|Font|Mouse|Key|Dx|Window")
EVENT_MODDING = re.compile(r"Plugin|Save|Load|Edu|GameDbs|GameInit|Tick|ExitToMenu|Worldpkg|NewGame|Parsed")


def relevance_of(m: Member) -> str:
    base = dict(DOMAINS).get(m.domain, "unknown")
    if m.kind == KIND_ENUM:
        if m.owner in ENUM_CAMPAIGN:
            return "campaign"
        return "ui" if m.owner in ENUM_UI else "battle"
    if m.kind == KIND_EVENT:
        if "Battle" in m.name:
            return "battle"
        if EVENT_MODDING.search(m.name):
            return "modding"
        return "ui" if EVENT_UI.search(m.name) else "campaign"
    if m.owner == "M2TWEOP" and re.match(r"(set|enable|unlock|toggle|use|ignore|no|hide|display|randomize|handle)[A-Z]",
                                         m.name):
        return "modding"  # engine tweaks, not game state
    if base == "campaign":
        w = words_of(m.name)
        if w & MODDING_WORDS:
            return "modding"
        if w & UI_WORDS:
            return "ui"
    return base


# --------------------------------------------------------------------------------------
# bridge scan
# --------------------------------------------------------------------------------------
# helper function (short or dotted name) -> the StateReport field it feeds
REPORT_KEYS = {
    "family_of": "family", "whereabouts": "family", "M.sight": "visible_enemies/seen_agents/nearby_settlements",
    "M.resources": "resources", "M.crossings": "crossings", "all_crossings": "crossings",
    "income_parts": "income_parts", "income": "income", "add_management": "settlements.(tax,order,queue,can_*)",
    "add_troops": "armies.troops", "army_view": "armies", "army_men": "armies", "agent_counts": "agent_limits",
    "agents_of": "agents", "recruit_queue_of": "settlements.recruit_queue", "queue_of": "settlements.queue",
    "M.mark_by_land": "nearby_settlements.by_land", "M.report": "(report body)",
    "construction_options": "settlements.can_build", "recruitment_options": "settlements.can_recruit",
    "agent_options": "settlements.can_recruit_agents", "building_levels": "settlements.buildings",
    "M.take_popups": "popups", "M.take_agent_news": "agent_results", "M.take_character_news": "character_news",
    "M.take_faction_news": "news", "M.take_stance_news": "stance_changes",
    "log_stance_changes": "stance_changes", "snapshot_stances": "stance_changes",
    "M.on_agent_mission": "agent_results", "M.on_character_event": "character_events",
    "M.on_faction_event": "news", "units_inside": "settlements.recruit_blocked", "leader_of": "armies.leader",
    "eyes_of": "distance", "distance": "distance", "traits_of": "(events: marriage offers)",
}


def blank_lua(text: str, keep_strings: bool = False) -> str:
    """Comments (and, unless keep_strings, string contents) replaced by spaces; newlines kept."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("--[[", i) or text.startswith("--[=[", i):
            close = "]]" if text.startswith("--[[", i) else "]=]"
            j = text.find(close, i)
            j = n if j < 0 else j + len(close)
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            if keep_strings:
                out.append(text[i : j + 1])
            else:
                out.append(c + " " * max(0, j - i - 1) + (c if j < n and text[j] == c else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


DEF_RE = re.compile(r"^(?:local\s+)?function\s+([\w.:]+)\s*\(", re.M)
ASSIGN_RE = re.compile(r"^(on[A-Z]\w*)\s*=", re.M)


def split_functions(text: str) -> dict[str, str]:
    """Top-level function name -> body text. Chunk-level code goes under '<main>'."""
    defs = list(DEF_RE.finditer(text))
    bodies: dict[str, str] = {}
    main = [text[: defs[0].start()]] if defs else [text]
    for i, d in enumerate(defs):
        end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
        name = d.group(1).replace(":", ".")
        bodies[name] = bodies.get(name, "") + text[d.start() : end]
    bodies["<main>"] = "".join(main)
    return bodies


TURN_DRIVERS = {"M.on_turn_start", "M.on_turn_end", "M.on_pre_battle"}


def roles_of_roots(names: list[str]) -> dict[str, str]:
    """Roots: M.report is the report, handlers.* are orders, M.on_* event handlers are events.
    Turn drivers and the M.take_* drains the report calls are reached, not roots."""
    roles = {}
    for n in names:
        if n == "M.report":
            roles[n] = "report"
        elif n.startswith("handlers."):
            roles[n] = "order"
        elif n not in TURN_DRIVERS and re.match(r"^M\.on_\w+|^on[A-Z]", n):
            roles[n] = "event"
    return roles


def reach(bodies: dict[str, str]) -> dict[str, set]:
    """function name -> roles (report/order/event/other) of the roots that reach it."""
    names = [n for n in bodies if n != "<main>"]
    calls: dict[str, set] = {}
    for n, b in bodies.items():
        c = set()
        for m in names:
            if m == n:
                continue
            pat = (r"(?<![\w.])" + re.escape(m) + r"\b") if "." in m else (r"(?<![\w.:])" + re.escape(m) + r"\b")
            if re.search(pat, b):
                c.add(m)
        calls[n] = c
    roles = roles_of_roots(names)
    # the report is also fed by every M.take_* style drain it calls: those are reached, not roots
    result: dict[str, set] = defaultdict(set)
    for root, role in roles.items():
        stack, seen = [root], set()
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            result[f].add(role)
            stack.extend(calls.get(f, ()))
    for n in names + ["<main>"]:
        if not result[n]:
            result[n].add("other")
    return result


# Lua variable names the bridge uses for each type. A member name that several types declare
# (`name`, `x`, `leader`) counts for the type whose variable it is read through; a read through
# an unknown variable is USED with a `?`. Hand-kept: extend when the bridge grows a new variable.
RECEIVER_HINTS = {
    "factionStruct": {"fac", "other", "faction", "f", "ownerFaction", "me"},
    "settlementStruct": {"s", "sett", "settlement"},
    "armyStruct": {"st", "army", "stack", "fleet"},
    "character": {"c", "leader", "agent", "char", "general", "fleader"},
    "characterRecord": {"nc", "namedCharacter", "leader"},
    "unit": {"u", "unit"},
    "tileStruct": {"tile", "t"},
    "regionStruct": {"r", "region"},
    "campaignStruct": {"campaign"},
    "stratMap": {"map"},
    "gameDataAll": {"gd"},
    "factionDiplomacy": {"d", "back"},
    "siegeStruct": {"sg", "siege"},
    "building": {"bld", "b"},
    "uiElementStruct": {"el", "leftover"},
    "eventTrigger": {"e", "eventData"},
    "M2TWEOP": {"M2TWEOP"},
    "stratmap": {"stratmap"},
    "stratmap.game": {"game"},
    "stratmap.camera": {"camera"},
    "gameSTDUI": {"gameSTDUI"},
}


def scan_bridge(paths: list[Path]):
    """Per-function bodies with the roles that reach them, plus the events the bridge defines."""
    bodies_all: dict[str, str] = {}
    strings_all: dict[str, str] = {}  # the same bodies with string literals kept
    events: set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        raw = p.read_text(errors="replace")
        text = blank_lua(raw)
        with_strings = split_functions(blank_lua(raw, keep_strings=True))
        for k, v in split_functions(text).items():
            key = k if k not in bodies_all else f"{p.name}:{k}"
            bodies_all[key] = v
            strings_all[key] = with_strings.get(k, "")
        events |= {m.group(1) for m in re.finditer(r"^function\s+(on[A-Z]\w*)\s*\(", text, re.M)}
        events |= {m.group(1) for m in ASSIGN_RE.finditer(text)}
    return bodies_all, strings_all, events


TABLE_RE = re.compile(r"([A-Za-z_][\w.]*)\s*=\s*\{([^{}]*)\}", re.S)


def find_key_tables(bodies: dict[str, str], strings: dict[str, str]) -> dict[str, dict[str, set]]:
    """key name -> {table: functions that mention the table}, for `T = { "key", key = "x" }` lists.
    A heuristic for members read through a variable (`e[k]`): no function names them directly."""
    out: dict[str, dict[str, set]] = defaultdict(dict)
    for defined_in, body in strings.items():
        for t in TABLE_RE.finditer(body):
            table, inner = t.group(1), t.group(2)
            keys = set(re.findall(r"[\"'](\w+)[\"']", inner)) | set(re.findall(r"\b(\w+)\s*=\s*[\"']", inner))
            if not keys:
                continue
            users = {f for f, b in bodies.items()
                     if re.search(r"(?<![\w.])" + re.escape(table) + r"\b", b)
                     and not (f == defined_in and f == "<main>")}  # the chunk-level list is not a use
            for k in keys:
                out[k].setdefault(table, set()).update(users)
    return out


def mark_usage(members: list[Member], bodies: dict[str, str], strings: dict[str, str],
               events_defined: set[str]) -> None:
    roles = reach(bodies)
    owners_of_name: dict[str, set] = defaultdict(set)
    for m in members:
        owners_of_name[m.name].add(m.owner)
    combined = {n: b for n, b in bodies.items()}
    key_tables = find_key_tables(bodies, strings)
    for m in members:
        if m.kind == KIND_EVENT:
            if m.name in events_defined:
                m.used_in.add("event")
            continue
        if m.kind == KIND_ENUM:
            pat = re.compile(r"(?<![\w.])" + re.escape(m.owner) + r"\.()" + re.escape(m.name) + r"\b")
        else:
            pat = re.compile(r"([\w)\]]+)\s*[.:]\s*" + re.escape(m.name) + r"\b")
        shared = len(owners_of_name[m.name]) > 1 and m.kind != KIND_ENUM
        sure_roles: set = set()
        maybe_roles: set = set()
        keys: set = set()
        for fname, body in combined.items():
            for hit in pat.finditer(body):
                recv = hit.group(1)
                if not shared:
                    verdict = "sure"
                elif recv in RECEIVER_HINTS.get(m.owner, ()):
                    verdict = "sure"
                elif any(recv in RECEIVER_HINTS.get(o, ()) for o in owners_of_name[m.name]):
                    continue  # the receiver is another type that has a member of this name
                else:
                    verdict = "maybe"
                (sure_roles if verdict == "sure" else maybe_roles).update(roles[fname])
                if verdict == "sure" and "report" in roles[fname] and fname in REPORT_KEYS:
                    keys.add(REPORT_KEYS[fname])
        if m.kind != KIND_ENUM:
            # read through a key table (`e[k]` over K.ECONOMY_IN = { "farmingIncome", ... }): the roles
            # are those of the functions that mention the table; a name shared between types is a maybe
            for table, fns in key_tables.get(m.name, {}).items():
                for fname in fns:
                    (maybe_roles if shared else sure_roles).update(roles[fname])
                    if not shared and "report" in roles[fname] and fname in REPORT_KEYS:
                        keys.add(REPORT_KEYS[fname])
        if sure_roles:
            m.used_in, m.report_keys = sure_roles, keys
        elif maybe_roles:
            m.used_in, m.ambiguous = maybe_roles, True


# --------------------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------------------
def status_text(m: Member) -> str:
    if not m.used:
        return "not used"
    parts = []
    for role in ("report", "order", "event", "other"):
        if role in m.used_in:
            if role == "report" and m.report_keys and not m.ambiguous:
                keys = sorted(m.report_keys - {"(report body)"})[:2]
                parts.append("report" + (f" ({', '.join(keys)})" if keys else ""))
            else:
                parts.append(role)
    s = "USED " + " + ".join(parts)
    if m.ambiguous:
        s += " ?"
    return s


def build(eop: Path, bridge_paths: list[Path]):
    members, enums, events = load_eop(eop)
    allm = members + enums + events
    for m in allm:
        m.domain = domain_of(m.owner)
        if m.owner in ("dipRelType",) or m.kind == KIND_ENUM:
            m.domain = "Enums and constants"
        m.relevance = relevance_of(m)
    bodies, strings, ev = scan_bridge(bridge_paths)
    mark_usage(allm, bodies, strings, ev)
    return allm, ev


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def short(s: str, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", s).strip().lstrip("- ").strip()
    return s if len(s) <= n else s[: n - 1] + "..."


def member_table(ms: list[Member]) -> list[str]:
    rows = ["| member | kind | what it is | status |", "|---|---|---|---|"]
    for m in ms:
        kind = m.kind + (f" {m.access}" if m.access else "")
        what = short(m.desc, 230 if m.kind == KIND_EVENT else 110) if m.desc else (f"`{m.type}`" if m.type else "")
        tag = "" if m.relevance in ("campaign", "") or m.domain == "Events" else f" *({m.relevance})*"
        rows.append(f"| `{m.name}`{tag} | {kind} | {esc(what)} | {status_text(m)} |")
    return rows


def render_markdown(allm: list[Member], version: str, ev_defined: set[str], gaps_md: str = "") -> str:
    by_dom: dict[str, list[Member]] = defaultdict(list)
    for m in allm:
        by_dom[m.domain].append(m)
    out: list[str] = []
    for dom, _ in DOMAINS:
        ms = by_dom.get(dom, [])
        if not ms:
            continue
        out.append(f"## {dom}\n")
        maybe = sum(1 for m in ms if m.used and m.ambiguous)
        out.append(f"{len(ms)} members, {sum(1 for m in ms if m.used and not m.ambiguous)} used"
                   + (f" (+{maybe} by name only)" if maybe else "") + ".\n")
        owners: dict[str, list[Member]] = defaultdict(list)
        for m in ms:
            owners[m.owner].append(m)
        collapse = dict(DOMAINS)[dom] in ("battle", "ui", "modding")
        if collapse:
            out.append("<details><summary>Show members</summary>\n")
        for owner in sorted(owners, key=lambda o: (-sum(x.used for x in owners[o]), o)):
            lst = owners[owner]
            out.append(f"### {owner} ({sum(x.used for x in lst)}/{len(lst)} used)\n")
            out += member_table(lst)
            out.append("")
        if collapse:
            out.append("</details>\n")
    return "\n".join(out)


def summary_rows(allm: list[Member]) -> list[str]:
    by_dom: dict[str, list[Member]] = defaultdict(list)
    for m in allm:
        by_dom[m.domain].append(m)
    rows = ["| domain | members | campaign-relevant | used | campaign-relevant used | campaign-relevant not used |",
            "|---|---:|---:|---:|---:|---:|"]
    tot = [0, 0, 0, 0, 0, 0]  # members, camp, used sure, used maybe, camp used sure, camp used maybe

    def used_txt(sure: int, maybe: int) -> str:
        return f"{sure}" + (f" (+{maybe}?)" if maybe else "")

    for dom, _ in DOMAINS:
        ms = by_dom.get(dom, [])
        if not ms:
            continue
        camp = [m for m in ms if m.relevance == "campaign"]
        sure = sum(1 for m in ms if m.used and not m.ambiguous)
        maybe = sum(1 for m in ms if m.used and m.ambiguous)
        csure = sum(1 for m in camp if m.used and not m.ambiguous)
        cmaybe = sum(1 for m in camp if m.used and m.ambiguous)
        rows.append(f"| {dom} | {len(ms)} | {len(camp)} | {used_txt(sure, maybe)} | {used_txt(csure, cmaybe)} | "
                    f"{len(camp) - csure - cmaybe} |")
        if dom != "Enums and constants":  # enum values are constants, not API surface: left out of the total
            tot = [tot[0] + len(ms), tot[1] + len(camp), tot[2] + sure, tot[3] + maybe, tot[4] + csure,
                   tot[5] + cmaybe]
    rows.append(f"| **Total, enums excluded** | **{tot[0]}** | **{tot[1]}** | **{used_txt(tot[2], tot[3])}** | "
                f"**{used_txt(tot[4], tot[5])}** | **{tot[1] - tot[4] - tot[5]}** |")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--eop", default=DEFAULT_EOP)
    ap.add_argument("--bridge", nargs="*", default=None)
    ap.add_argument("--md", help="write the full member listing and summary to this file")
    ap.add_argument("--head", help="hand-written intro for --md (default scripts/eop_coverage_head.md)")
    ap.add_argument("--json", help="write every member as JSON")
    ap.add_argument("--types", action="store_true", help="list usertypes with their domain and counts")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    bridges = [Path(b) for b in args.bridge] if args.bridge else [root / b for b in BRIDGES]
    eop = Path(args.eop)
    if not (eop / LIB).exists():
        print(f"EOP source not found at {eop / LIB}", file=sys.stderr)
        return 2
    allm, ev = build(eop, bridges)
    version = eop_version(eop)
    if args.types:
        c = Counter((m.owner, m.domain) for m in allm)
        for (o, d), n in sorted(c.items(), key=lambda x: (x[0][1], x[0][0])):
            print(f"{d:45} {o:35} {n}")
    if args.json:
        Path(args.json).write_text(json.dumps([
            {**{k: v for k, v in m.__dict__.items() if k not in ("used_in", "report_keys")},
             "used_in": sorted(m.used_in), "report_keys": sorted(m.report_keys)} for m in allm], indent=1))
    if args.md:
        head_path = Path(args.head) if args.head else root / "scripts" / "eop_coverage_head.md"
        head = head_path.read_text() if head_path.exists() else ""
        api = [m for m in allm if m.kind != KIND_ENUM]
        camp = [m for m in api if m.relevance == "campaign"]
        evs = [m for m in allm if m.kind == KIND_EVENT]
        head = (head.replace("{{VERSION}}", version).replace("{{TOTAL}}", str(len(api)))
                .replace("{{EVENTS}}", str(len(evs))).replace("{{EVENTS_USED}}", str(sum(m.used for m in evs)))
                .replace("{{CAMPAIGN}}", str(len(camp)))
                .replace("{{USED}}", str(sum(m.used and not m.ambiguous for m in api)))
                .replace("{{USED_MAYBE}}", str(sum(m.used and m.ambiguous for m in api)))
                .replace("{{CAMPAIGN_USED}}", str(sum(m.used and not m.ambiguous for m in camp)))
                .replace("{{CAMPAIGN_USED_MAYBE}}", str(sum(m.used and m.ambiguous for m in camp))))
        body = (head + "\n## Summary by domain\n\n" + "\n".join(summary_rows(allm)) + "\n\n"
                + render_markdown(allm, version, ev))
        Path(args.md).write_text(body)
    api = [m for m in allm if m.kind != KIND_ENUM]
    camp = [m for m in api if m.relevance == "campaign"]
    print(f"EOP {version}: {len(api)} members (+{len(allm) - len(api)} enum values), "
          f"{len(camp)} campaign-relevant; used {sum(m.used and not m.ambiguous for m in api)} "
          f"(+{sum(m.used and m.ambiguous for m in api)} by name only), campaign-relevant used "
          f"{sum(m.used and not m.ambiguous for m in camp)} (+{sum(m.used and m.ambiguous for m in camp)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
