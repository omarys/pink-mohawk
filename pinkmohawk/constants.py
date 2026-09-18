"""Every number from docs/design/DECISIONS.md, named, with its section for traceability.

This module imports nothing and holds no logic. If a value here disagrees with
`docs/design/DECISIONS.md`, the document wins and this file is wrong.

Phase 1 needs everything down to the CLOCK section. ECONOMY is Phase 2 and is marked; it is
included because the contract fixes those values and re-deriving them later is how drift starts.
"""

# fmt: off  --  hand-aligned contract tables: the columns of DECISIONS references are the point
# of this file, and the formatter would collapse them to single spaces.

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Geometry and rendering — DECISIONS §9, §12
# ---------------------------------------------------------------------------
TILE_PX: Final = 16
VIEW_W: Final = 80  # map viewport columns
VIEW_H: Final = 38  # map viewport rows
UI_ROWS: Final = 7  # rows 38-44
SCREEN_W: Final = VIEW_W
SCREEN_H: Final = VIEW_H + UI_ROWS  # 45 rows = 720px at 16px tiles
SITE_W: Final = 60  # a Site is camera-scrolled, not one screen
SITE_H: Final = 60
FOV_RADIUS: Final = 8
FOV_RADIUS_DARK: Final = 2  # lights hacked off, enemies only — DECISIONS §7

# ---------------------------------------------------------------------------
# Attributes and skills — DECISIONS §1, §2
# ---------------------------------------------------------------------------
ATTRIBUTES: Final = (
    "body",
    "agility",
    "reaction",
    "strength",
    "willpower",
    "logic",
    "intuition",
    "charisma",
)
ATTRIBUTE_CAP: Final = 6
ADEPT_RAISABLE: Final = ("agility", "strength")  # the Adept may Advance these to 7
ADEPT_CAP: Final = 7

# skill -> linked attribute
SKILLS: Final = {
    "firearms": "agility",
    "close_combat": "agility",
    "athletics": "agility",
    "stealth": "agility",
    "perception": "intuition",
    "sorcery": "tradition",  # resolved per class: Mage/Shaman tradition attribute
    "conjuring": "charisma",
    "cybercombat": "logic",
    "electronics": "logic",
    "medicine": "logic",
    "negotiation": "charisma",
    "con": "charisma",
    "intimidation": "charisma",
}
SKILL_CAP: Final = 6

# ---------------------------------------------------------------------------
# Dice resolution — DECISIONS §3
# ---------------------------------------------------------------------------
HIT_MIN: Final = 5  # 5 or 6 is a Hit
THRESHOLDS: Final = {"trivial": 1, "average": 2, "hard": 3, "extreme": 4}
GLITCH_STRICTLY_MORE_THAN_HALF_ONES: Final = (
    True  # printings disagree; contract picks "more than half"
)


# ---------------------------------------------------------------------------
# Damage — DECISIONS §4
# ---------------------------------------------------------------------------
def physical_boxes(body: int) -> int:
    """8 + ceil(Body / 2)."""
    return 8 + -(-body // 2)


def stun_boxes(willpower: int) -> int:
    """8 + ceil(Willpower / 2)."""
    return 8 + -(-willpower // 2)


WOUND_PENALTY_PER_BOXES: Final = 3  # -1 die per 3 filled boxes, counting both tracks
WOUND_PENALTY_PER_STEP: Final = 1
OVERFLOW_STUN_PER_PHYSICAL: Final = 2  # 2 Stun boxes convert to 1 Physical
COVER_BONUS: Final = 2  # a cell adjacent to a blocking tile, LOS blocked from the attacker

DAMAGE_PHYSICAL: Final = "P"
DAMAGE_STUN: Final = "S"

# Terrain ids. 0 = wall is load-bearing: an out-of-bounds read returns 0, so FOV, A* and the flow
# maps never need a bounds branch to treat the map edge as solid (data-model.md §1).
TILE_WALL: Final = 0
TILE_FLOOR: Final = 1

# name -> (damage code, rating, ap as a POSITIVE magnitude, range in cells)
WEAPONS: Final = {
    "heavy_pistol": (5, "P", 1, 8),
    "smg": (6, "P", 0, 10),
    "assault_rifle": (8, "P", 2, 14),
    "shotgun": (7, "P", 1, 6),
    "katana": ("strength+3", "P", 3, 1),
    "stun_baton": (6, "S", 0, 1),
    "hellhound_bite": ("strength+2", "P", 1, 1),
}
# a P attack becomes Stun when its modified DV is less than the modified armour; S is always Stun
ARMOUR: Final = {"armoured_vest": 6, "lined_coat": 7, "armoured_jacket": 8, "helmet": 2}
MAGAZINES: Final = {"heavy_pistol": 15, "smg": 30, "assault_rifle": 30, "shotgun": 8}

# ---------------------------------------------------------------------------
# Turns: Initiative Score as Energy — DECISIONS §5
# ---------------------------------------------------------------------------
INITIATIVE_DICE_BASE: Final = 1  # 1d6
INITIATIVE_DICE_MAX: Final = 2  # +1d6 per Improved Reflexes rating, capped here in v1
PASS_DROP: Final = 10  # Score -= 10 per Pass
PASS_END_THRESHOLD: Final = 1  # a Pass ends when a Step is unaffordable; see §14 resolved 15
MAX_ENERGY: Final = 63  # bucket-array bound for the scheduler (data-model §5)

# action -> Energy cost
ENERGY_COSTS: Final = {
    "step": 1,
    "sprint_per_3_tiles": 2,
    "attack": 10,
    "use_power": 10,
    "cast": 10,
    "hack": 10,
    "aim": 5,
    "reload": 5,
    "take_cover": 5,
    "use_item": 5,
    "stand_up": 5,
}
AIM_MAX_BONUS: Final = 2
SPRINT_DEFENCE_PENALTY: Final = -2

# ---------------------------------------------------------------------------
# Edge, Qi, Drain — DECISIONS §6
# ---------------------------------------------------------------------------
EDGE_POINTS: Final = 3

QI_MAX: Final = 4
QI_REFRESH_PER_PASS: Final = 1
QI_POWERS: Final = {  # power -> Qi cost
    "improved_reflexes": 2,
    "killing_hands": 1,
    "wall_run": 1,
    "mystic_armor": 1,
    "attribute_boost": 1,
}
DURATION_ROUNDS: Final = 3  # default power/spell duration in rounds

FORCE_MIN: Final = 1
FORCE_MAX: Final = 8  # Force > the Tradition Attribute value makes Drain Physical
SUSTAIN_MAX: Final = 2
SUSTAIN_PENALTY: Final = -2  # per sustained spell, on everything else

TRADITION_ATTRIBUTE: Final = {"mage": "logic", "shaman": "charisma", "decker": "logic"}

# Ability -> Drain as (floor, Force offset). Drain = max(floor, Force - offset).
# Summoning and hacking are handled separately below.
DRAIN_FORMULAS: Final = {
    "manabolt": (2, 3),
    "stunball": (3, 2),
    "heal": (3, 1),
    "analyze_device": (1, 4),
    "invisibility": (2, 2),
    "armor": (2, 2),
    "fear": (2, 2),
    "ward": (2, 3),
}
SUMMON_DRAIN_FLOOR: Final = 2  # Drain = 2 x the Spirit's Hits, minimum 2
SPIRIT_DURATION_ROUNDS: Final = 3

# ---------------------------------------------------------------------------
# Device hacking — DECISIONS §7
# ---------------------------------------------------------------------------
DEVICE_RATINGS: Final = {
    "gun": 2,
    "optics": 2,
    "door": 2,  # 2-4 in practice
    "lock": 2,
    "lights": 3,
    "commlink": 3,
    "drone": 4,
    "cyberware": 4,
}
HACK_DRAIN_DIVISOR: Final = 2  # ceil(rating / 2), doubled on a Glitch
SCAN_RADIUS: Final = 12
DEVICE_CARRY_CAP: Final = 3  # per enemy
RATING4_PER_NODE_CAP: Final = 2  # per Mission Graph node
HACK_DRAIN_PER_NODE_CAP: Final = 6

# ---------------------------------------------------------------------------
# Spirits — DECISIONS §4, §7
# ---------------------------------------------------------------------------
# name -> (ability id, DV as (floor, Force offset), ap, range, is_stun)
SPIRIT_ATTACKS: Final = {
    "beast": ("beast_strike", (3, 0), 1, 1, False),
    "air": ("air_bolt", (1, 0), 0, 8, False),
    "earth": ("earth_slam", (2, 0), 2, 1, False),
    "water": ("water_burst", (0, 0), 0, 6, True),
}

# ---------------------------------------------------------------------------
# Security Clock — DECISIONS §9
# ---------------------------------------------------------------------------
CLOCK_SEGMENTS: Final = 10
CLOCK_TICKS: Final = {
    "gunfire": 2,
    "guard_killed": 2,
    "body_found": 3,
    "failed_hack": 1,
    "loud_spell": 2,  # Force >= 4
    "alarm_tripped": 2,
    "lock_forced": 1,
    "silent_takedown": 0,
    "successful_hack": 0,
}
ALERT_THRESHOLD: Final = 4  # alert_level 1
LOCKDOWN_THRESHOLD: Final = 7  # alert_level 2
CONVERGE_THRESHOLD: Final = 10  # forced extraction
ALERT_LEVEL_CALM: Final = 0
ALERT_LEVEL_ALERT: Final = 1
ALERT_LEVEL_LOCKDOWN: Final = 2

# ---------------------------------------------------------------------------
# Blackboard — DECISIONS §8. Twelve typed keys; the board is a fixed struct, not a dict.
# ---------------------------------------------------------------------------
BLACKBOARD_KEYS: Final = (
    "target",
    "last_known_pos",
    "home_pos",
    "cover_pos",
    "noise_pos",
    "alert_level",
    "morale",
    "objective",
    "pacified",
    "command_target",
    "summoner_id",
    "rounds_bound",
)
UTILITY_WEIGHTS: Final = ("w_threat", "w_visible", "w_objective", "w_ally_risk")
HYSTERESIS_MIN: Final = 0.05
HYSTERESIS_MAX: Final = 0.25

# A Repeat with a never-changing condition spins inside one decision step while spending no Energy.
# The cap turns that hang into a diagnosable error rather than a frozen scheduler.
MAX_TICKS_PER_STEP: Final = 64

# Unplaytested defaults from DECISIONS §8. None means the archetype has no such branch.
ARCHETYPE_WEIGHTS: Final = {
    "corp_guard": {
        "w_threat": 1.0,
        "w_visible": 2.0,
        "w_objective": 1.5,
        "w_ally_risk": 3.0,
        "hysteresis": 0.10,
        "morale_bonus": 1,
        "flee_threshold": -4,
    },
    "security_drone": {
        "w_threat": 1.2,
        "w_visible": 3.0,
        "w_objective": 1.0,
        "w_ally_risk": 2.0,
        "hysteresis": 0.15,
        "morale_bonus": None,
        "flee_threshold": None,
    },
    "ganger": {
        "w_threat": 1.5,
        "w_visible": 1.5,
        "w_objective": 0.5,
        "w_ally_risk": 2.5,
        "hysteresis": 0.05,
        "morale_bonus": 0,
        "flee_threshold": -3,
    },
    "corp_mage": {
        "w_threat": 0.8,
        "w_visible": 2.5,
        "w_objective": 1.0,
        "w_ally_risk": 3.5,
        "hysteresis": 0.20,
        "morale_bonus": 0,
        "flee_threshold": -4,
    },
    "hellhound": {
        "w_threat": 2.0,
        "w_visible": 2.0,
        "w_objective": 1.0,
        "w_ally_risk": 0.5,
        "hysteresis": 0.25,
        "morale_bonus": None,
        "flee_threshold": None,
    },
    "spirit": {
        "w_threat": 2.0,
        "w_visible": 2.0,
        "w_objective": 1.0,
        "w_ally_risk": 1.0,
        "hysteresis": 0.10,
        "morale_bonus": None,
        "flee_threshold": None,
    },
}

# ---------------------------------------------------------------------------
# Enemies — names only; stat blocks live in docs/design/enemies.md
# ---------------------------------------------------------------------------
ENEMY_ARCHETYPES: Final = ("corp_guard", "security_drone", "ganger", "corp_mage", "hellhound")

# ---------------------------------------------------------------------------
# ECONOMY — DECISIONS §9. Phase 2, fixed here because the contract fixes it.
# ---------------------------------------------------------------------------
BASE_PAYOUT: Final = 12_000
PAYOUT_PER_NET_NEGOTIATION_HIT: Final = 100
HEAT_MAX: Final = 20
HEAT_DECAY_PER_SUCCESS: Final = 1
HEAT_VALVE_THRESHOLD: Final = 8  # -2 decay above this
HEAT_VALVE_DECAY: Final = 2
HEAT_FORCED_EXTRACTION: Final = 2
CLINIC_PER_BOX: Final = 250
REP_VOLUNTARY_EXTRACTION: Final = 1
REP_FORCED_EXTRACTION: Final = -1

GEAR_PRICES: Final = {
    "heavy_pistol": 1_200,
    "smg": 2_400,
    "assault_rifle": 4_800,
    "shotgun": 3_000,
    "katana": 1_500,
    "stun_baton": 900,
    "ammunition": 100,
    "medkit": 500,
    "armoured_vest": 1_000,
    "lined_coat": 2_000,
    "armoured_jacket": 3_500,
    "helmet": 600,
    "cyberdeck": 8_000,  # without it the Decker's device table is unavailable
}

# ---------------------------------------------------------------------------
# Progression — DECISIONS §6, §14
# ---------------------------------------------------------------------------
XP_PER_SUCCESS: Final = 1
XP_PER_FAILURE: Final = 5  # one payout per obstacle
ADVANCE_COST_SKILL_PER_RATING: Final = 3  # new rating x 3
ADVANCE_COST_ATTRIBUTE_PER_RATING: Final = 5
PERK_DUPLICATE_XP: Final = 3
MAGAZINE_RELOAD_COST: Final = 100

# fmt: on
