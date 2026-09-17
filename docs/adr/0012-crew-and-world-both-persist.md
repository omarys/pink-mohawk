# Crew and world both persist across Jobs

Between Runs the Crew keeps its sheets, Perks, gear, and nuyen; the world keeps Heat and faction and Fixer reputation. Only the Run resets: Site layout, enemy placement, and the Security Clock are generated fresh from a seed. This is what makes failure-driven growth and Clock losses accumulate into something instead of evaporating.

**Considered options**: reset the crew each Job, persisting only unlocks (rejected: inverted XP and Perks stop meaning anything); persist gear but reset the world (rejected: failure then costs only money and the Clock has no memory); persist the world but rebuild the crew (rejected: nobody to grow attached to).

**Consequences**: two persistent state graphs must be versioned for saves, and Heat creates an intended difficulty spiral that needs floor and ceiling — a crew on a losing streak needs a way back down, or the campaign becomes unwinnable rather than tense.
