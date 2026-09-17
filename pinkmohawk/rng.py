"""Deterministic seeding — DECISIONS §9, §10.

One scheme for the whole project: `derive(seed, name)` over sha256, into named per-subsystem
streams. This module imports nothing but the stdlib, which is what lets it sit in layer 0.

Why the builtin `hash()` is banned
---------------------------------
`hash()` on str is salted per process via PYTHONHASHSEED, so `hash((run_seed, actor_id))`
produces a different value in every interpreter. A save that reproduces its Site in one run and
a different Site in the next is not a save. That bug appeared once in the design docs (ai.md's
target choice) and the `demo()` below exists specifically to catch it if it comes back.

Why streams are named, not numbered
-----------------------------------
`seed_graph = site_seed ^ 0x01` couples two subsystems: change what the graph stream draws and
the embed stream shifts with it. Independent streams derived from one root mean a change to
generation cannot perturb combat, and a seeded Run stays reproducible subsystem by subsystem.

    .venv/bin/python -m pinkmohawk.rng      # runs demo()
"""

from __future__ import annotations

import hashlib
import random
import secrets
import subprocess
import sys
from typing import Final

# The streams that exist in v1. Adding one means adding it here, so the set stays enumerable.
STATIC_STREAMS: Final = frozenset({
    "gen.graph",
    "gen.embed",
    "gen.place",
    "rules.initiative",
    "rules.combat",
    "loot",
})

_DIGEST_BYTES: Final = 8  # 64 bits, comfortably inside a Random seed


def derive(seed: int, name: str) -> int:
    """Return a deterministic 64-bit integer for (seed, name). Never uses hash()."""
    material = f"{seed}:{name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:_DIGEST_BYTES], "big")


def campaign_seed() -> int:
    """Create the root seed once, at campaign start. Store it on the save."""
    return secrets.randbits(64)


def run_seed(root: int, job_id: str, run_counter: int) -> int:
    """The seed for one Run. Derived once at Depart, then stored — never recomputed on load."""
    return derive(root, f"run:{job_id}:{run_counter}")


def hub_stream(root: int, hub_day: int, name: str) -> int:
    """A Hub-side draw (shop stock and friends), namespaced away from the Run streams."""
    return derive(root, f"hub:{hub_day}:{name}")


def make_static_rngs(seed: int) -> dict[str, random.Random]:
    """One Random per static stream, all derived from the same root."""
    return {name: random.Random(derive(seed, name)) for name in sorted(STATIC_STREAMS)}


def actor_rng(seed: int, actor_id: int) -> random.Random:
    """Per-actor stream. Every actor's draws are independent of every other actor's."""
    return random.Random(derive(seed, f"ai:{actor_id}"))


def spawn_stream(seed: int, name: str) -> random.Random:
    """Catch-all for a parameterised stream such as an embedding retry: `gen.embed:2`."""
    return random.Random(derive(seed, name))


def demo() -> None:
    """Runnable self-check. The subprocess part is the one that matters: it fails if anyone
    reintroduces the builtin hash(), because that is salted per process."""
    seed = 123456789
    assert derive(seed, "gen.graph") == derive(seed, "gen.graph"), "not deterministic"
    assert derive(seed, "gen.graph") != derive(seed, "gen.embed"), "streams are not distinct"
    assert derive(seed, "gen.graph") != derive(seed + 1, "gen.graph"), "seed is ignored"
    assert 0 <= derive(seed, "x") < 2**64, "outside 64-bit range"

    # independence: identical stream names under different roots must not collide
    roots = [campaign_seed() for _ in range(4)]
    assert len(set(roots)) == 4, "campaign_seed collided"
    graph = [derive(r, "gen.graph") for r in roots]
    assert len(set(graph)) == 4, "stream collided across roots"

    # the same seed must produce the same first draw, in a fresh interpreter with a different
    # PYTHONHASHSEED. This is the property hash() silently breaks.
    probe = (
        "import sys;sys.path.insert(0,'.');"
        "from pinkmohawk.rng import derive,make_static_rngs;"
        "print(derive(123456789,'gen.graph'),"
        "      make_static_rngs(123456789)['loot'].random())"
    )
    outputs = set()
    for hashseed in ("0", "1", "random"):
        done = subprocess.run([sys.executable, "-c", probe],
                              capture_output=True, text=True, check=True,
                              env={"PYTHONHASHSEED": hashseed, "PATH": "", "PYTHONPATH": "."})
        outputs.add(done.stdout.strip())
    assert len(outputs) == 1, f"seed derivation is not process-stable: {outputs}"

    r = make_static_rngs(seed)
    assert set(r) == set(STATIC_STREAMS), "registry mismatch"
    assert r["loot"].random() != r["gen.graph"].random(), "streams are not independent"

    print(f"OK  derive() stable across PYTHONHASHSEED {sorted(outputs)[0]!r}; "
          f"{len(STATIC_STREAMS)} static streams")


if __name__ == "__main__":
    demo()
