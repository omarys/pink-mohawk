"""The campaign save: one slot, schema-versioned, written atomically.

ADR-0012 and world.md §10 keep two state graphs and one file, and this module is the file. It is
deliberately thin: `campaign.CampaignState` owns the document's shape and world.md §10.4 owns its
keys, so what lives here is the *policy* — where the slot is, which versions this build will read,
and how a write is made safe.

Phase 2 writes `schema_version` and refuses everything else. Roadmap's Phase 2 non-goal is "no save
migration (schema bump logic is Phase 4)", so an older file is an error rather than a silent upgrade;
§13's `vN -> vN+1` chain arrives in Phase 4. Refusing a *newer* file is the document's own rule
("refuse to load a save newer than the build") and it is the one that stops a downgrade from eating a
campaign this build cannot represent.

The write is atomic — a temporary file in the same directory, then `os.replace`. A crash mid-write
can then lose the write; it can never truncate the campaign that was there. There is no manual save
and no mid-Run save (§10.5), which is what gives Heat its meaning without permadeath.

`SCHEMA_VERSION` is this module's, and world.md §10.4 owns its value. `campaign.RNG_NOTE` is the
document's string, imported rather than restated: the note exists only to be compared on load.

Layer 3: imports `campaign` and `errors`. No tcod.

    .venv/bin/python -m pinkmohawk.save      # the acceptance test
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import Any, Final

from . import campaign
from .constants import GEAR_PRICES
from .errors import RuntimeFailure, ValidationError

#: world.md §10.4: "an integer `schema_version`". Bump it only with a migration behind it.
SCHEMA_VERSION: Final = 1

ROOT: Final = pathlib.Path(__file__).resolve().parent.parent

#: §10.5's single slot. `saves/` is created on demand and is not version control's business.
DEFAULT: Final = ROOT / "saves" / "campaign.json"


def save(state: campaign.CampaignState, path: pathlib.Path = DEFAULT) -> pathlib.Path:
    """Write the slot and return the path written.

    The temporary file is a sibling of the target, so the rename is within one filesystem and
    therefore atomic; the previous campaign survives any crash before it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = state.to_save_dict(SCHEMA_VERSION)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n")
    os.replace(temporary, path)
    return path


def load(path: pathlib.Path = DEFAULT) -> campaign.CampaignState:
    """Read the slot, refusing anything this build cannot faithfully represent."""
    if not path.exists():
        raise ValidationError([f"no save at {path} (§10.5's slot)"])
    try:
        document: Any = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValidationError([f"{path}: not valid JSON ({exc})"]) from exc
    if not isinstance(document, dict):
        raise ValidationError([f"{path}: the save must be a JSON object"])
    version = document.get("schema_version")
    if not isinstance(version, int):
        raise ValidationError([f"{path}: schema_version is {version!r}, not an integer"])
    if version > SCHEMA_VERSION:
        raise RuntimeFailure(
            [
                f"{path} was written by a newer build: schema_version {version} > "
                f"{SCHEMA_VERSION}. Refusing to load it rather than guess at the extra fields."
            ]
        )
    if version < SCHEMA_VERSION:
        raise RuntimeFailure(
            [
                f"{path} is schema_version {version} and this build is {SCHEMA_VERSION}. Phase 2 "
                f"has no migration (roadmap non-goal); §13's vN -> vN+1 chain is Phase 4's."
            ]
        )
    note = document.get("rng_note")
    if note != campaign.RNG_NOTE:
        raise RuntimeFailure(
            [
                f"{path} was written under rng_note {note!r}, not {campaign.RNG_NOTE!r}. Every seed "
                f"in it derives differently here, so the campaign would not replay (§10.4)."
            ]
        )
    return campaign.CampaignState.from_save_dict(document)


def exists(path: pathlib.Path = DEFAULT) -> bool:
    """Whether the slot holds a save. The Hub asks this to choose New Game or Continue."""
    return path.exists()


# ==============================================================================================
# Acceptance test
# ==============================================================================================
def demo() -> None:
    """Roadmap Phase 2, point 5: a save round-trips, and anything else is refused loudly."""
    with tempfile.TemporaryDirectory() as directory:
        slot = pathlib.Path(directory) / "nested" / "campaign.json"
        assert not exists(slot), "nothing is saved yet"

        state = campaign.new_campaign(20260918)
        state.runners[0].perks.append(campaign.Perk("perk_sure_grip", "lock:job_014:node_sec_2"))
        state.runners[1].stun, state.runners[1].physical = 2, 3
        state.stash.append(campaign.StashEntry("medkit", 2))
        state.heat = 5
        state.rep_fixer = 3
        state.rep_factions["corp_arasaka"] = -1
        state.mark_flag("met_fixer")
        job = state.begin_job(state.offers[0].id)
        state.legwork_buy_gear("armoured_vest", GEAR_PRICES["armoured_vest"])
        state.change_rep("fixer", 1)

        # ---- 1. write, then read it back --------------------------------------------------------
        written = save(state, slot)
        assert written == slot and slot.exists(), "save() creates the directory it needs"
        assert not slot.with_name(slot.name + ".tmp").exists(), "the temporary file is gone"
        assert exists(slot)

        loaded = load(slot)
        assert isinstance(loaded, campaign.CampaignState)
        assert loaded.seed == state.seed, "the root seed survives, so every Site still derives"
        assert loaded.nuyen == state.nuyen and loaded.heat == state.heat == 5
        assert loaded.rep_fixer == state.rep_fixer == 4, "3 + 1 from the change_rep above"
        assert loaded.rep_factions == {"corp_arasaka": -1}
        assert loaded.flags == {"met_fixer": True}
        assert loaded.stash == [
            campaign.StashEntry("medkit", 2),
            campaign.StashEntry("armoured_vest", 1),
        ]
        assert loaded.runners[0].perks == [
            campaign.Perk("perk_sure_grip", "lock:job_014:node_sec_2")
        ], "a Perk keeps the obstacle that paid it (ADR-0006)"
        assert (loaded.runners[1].stun, loaded.runners[1].physical) == (2, 3)
        assert loaded.active is not None and loaded.active.run_seed == job.run_seed
        assert loaded.active.id == job.id and loaded.active.run_counter == job.run_counter
        assert loaded.active.buy_gear == 1, "Legwork survives the round trip"
        assert [offer.id for offer in loaded.offers] == [offer.id for offer in state.offers]
        assert loaded.has_item("armoured_vest"), "gear bought at the Hub is in the stash"
        loaded.bind_pc("shaman")
        assert loaded.get("attr.charisma") == 6 and loaded.get("skill.conjuring") == 5

        # ---- 2. the file itself is §10.4's document ---------------------------------------------
        document = json.loads(slot.read_text())
        assert set(document) == {
            "schema_version",
            "saved_at",
            "rng_note",
            "campaign",
            "crew",
            "world",
            "job",
        }
        assert document["schema_version"] == SCHEMA_VERSION == 1
        assert document["rng_note"] == campaign.RNG_NOTE
        assert document["crew"]["nuyen"] == state.nuyen
        assert "seed" in document["campaign"], "rng.campaign_seed says to store the root seed"
        assert document["crew"]["runners"][0]["class"] == "physical_adept"

        # ---- 3. writing twice changes nothing but the timestamp ---------------------------------
        save(state, slot)
        again = load(slot)
        assert again.to_save_dict(SCHEMA_VERSION, saved_at="x") == loaded.to_save_dict(
            SCHEMA_VERSION, saved_at="x"
        ), "a second write is idempotent"

        # ---- 4. version and RNG policy: refuse rather than guess ---------------------------------
        newer = dict(document)
        newer["schema_version"] = SCHEMA_VERSION + 1
        slot.write_text(json.dumps(newer))
        try:
            load(slot)
        except RuntimeFailure as exc:
            assert str(SCHEMA_VERSION + 1) in str(exc) and str(SCHEMA_VERSION) in str(exc), str(exc)
        else:  # pragma: no cover - a failure here is the assert
            raise AssertionError("a save from a newer build must be refused")

        older = dict(document)
        older["schema_version"] = SCHEMA_VERSION - 1
        slot.write_text(json.dumps(older))
        try:
            load(slot)
        except RuntimeFailure as exc:
            assert "migration" in str(exc), "an older save is refused until Phase 4 migrates it"
        else:  # pragma: no cover
            raise AssertionError("an older save must be refused, not silently upgraded")

        renamed = dict(document)
        renamed["rng_note"] = "some-other-rng/1.0"
        slot.write_text(json.dumps(renamed))
        try:
            load(slot)
        except RuntimeFailure as exc:
            assert "rng_note" in str(exc), "the note exists to be compared"
        else:  # pragma: no cover
            raise AssertionError("a save written under another RNG must be refused")

        # ---- 5. a damaged slot fails with a message, not a traceback -----------------------------
        slot.write_text("{ this is not json")
        try:
            load(slot)
        except ValidationError as exc:
            assert "not valid JSON" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("malformed JSON must be a ValidationError")

        slot.write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, "rng_note": campaign.RNG_NOTE})
        )  # version and note are fine; the roots are what is missing
        try:
            load(slot)
        except ValidationError as exc:
            assert "campaign" in str(exc), "the missing roots are all named at once"
        else:  # pragma: no cover
            raise AssertionError("a save missing its roots must be refused")

        slot.unlink()
        try:
            load(slot)
        except ValidationError as exc:
            assert "no save" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("an absent slot must be an error, not an empty campaign")

    print(
        f"OK  save: schema_version {SCHEMA_VERSION} round-trips a campaign and refuses "
        f"{SCHEMA_VERSION + 1}, older versions, a foreign rng_note, malformed JSON and a missing slot"
    )


if __name__ == "__main__":
    demo()
