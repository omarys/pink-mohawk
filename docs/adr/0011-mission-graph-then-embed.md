# Sites are generated objective-first: build the Mission Graph, then embed it

Generation runs in two stages. First build the Mission Graph — typed nodes (entry, security, objective, side, exit) connected so that every objective is reachable and the shape of the Job is legible. Then embed that graph into a tile map: each node becomes a room sized by its type, edges become corridors, and the extras (devices, enemies, loot) are placed by node type. Failure mode avoided: a vault adjacent to the entrance, or a Run with no reason for its own layout.

**Considered options**: recursive BSP rooms and corridors (rejected: robust but objective-blind, so placement is post-hoc scatter); cellular automata caves (rejected: wrong shape for offices and corporate floors, which is most of what a shadowrun targets); authored rooms recombined (rejected for v1: the authoring burden grows with every new Job type).

**Consequences**: map layout quality now depends on graph quality, so a boring graph produces a boring Site no matter how good the room generator is. It also creates the project's richest algorithm exercise: graph construction, connectivity, and embedding.
