# Dialogue is a custom JSON graph with a hand-written runner

Conversations are node graphs in JSON — line, choice, condition, and command nodes — advanced by a small runner we write. Conditions read the same variable store the Behavior Trees read, so an NPC's dialogue can branch on the same facts its AI acts on. NPC dialogue is explicitly a scripting exercise and a learning goal, not a solved problem to import.

**Considered options**: Ink with a Python runtime (rejected: a second language and a dependency for a system we want to build, and narrative state would live outside Python); Yarn Spinner (rejected: Python runtime support is thin, so integration is its own project); plain Python callables per NPC (rejected: dialogue becomes code, every NPC reimplements the plumbing, and there is no data schema to validate).

**Consequences**: we own authoring ergonomics, validation, and error messages for our own format — the cost of not adopting a proven tool. The guidance we follow is deliberately narrow: build a graph and an interpreter for it, never a language.
