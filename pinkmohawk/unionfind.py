"""Disjoint sets: union by size with path compression.

DECISIONS §13 (Mission Graph, Embedding rows); rationale in docs/design/data-model.md §6, §7.

Two jobs in this project, both as an acceptance gate rather than as a search:
  * `embed` — is every room reachable from the entry? Every room and every carved corridor is an
    edge in the site graph; one pass at the end says yes or no in near-constant time per edge.
  * `mission_graph` — did adding this side branch create a cycle back onto the spine?

`find` is iterative on purpose. A recursive version is shorter, but a long chain of unions before
the first compression puts O(n) frames on the stack, and this structure's whole value is that it
never degrades. Path halving (`parent[a] = parent[parent[a]]`) gets the same practical flattening
without a second traversal, so there is no reason to hold a `rank`/`size` array *and* compress —
we keep `size` because union by size is what bounds the depth before compression ever runs.

Amortized cost per operation is O(alpha(n)) — inverse Ackermann, under 5 for any n that fits in
this universe. Both operations are effectively O(1); the point of the structure is that a naive
"can A reach B" DFS per query would be O(V) each time.

    .venv/bin/python -m pinkmohawk.unionfind      # runs demo()
"""

from __future__ import annotations


class DisjointSet:
    """Union-find over the integers 0..n-1."""

    __slots__ = ("parent", "size", "_count")

    def __init__(self, n: int) -> None:
        if n < 0:
            raise ValueError("n must be non-negative")
        self.parent = list(range(n))
        self.size = [1] * n
        self._count = n

    @property
    def count(self) -> int:
        """Number of disjoint sets remaining."""
        return self._count

    def find(self, a: int) -> int:
        """Root of a's set, compressing as it walks. Iterative: no stack to blow."""
        parent = self.parent
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:          # second pass: point everything straight at the root
            parent[a], a = root, parent[a]
        return root

    def union(self, a: int, b: int) -> bool:
        """Merge the two sets. Returns False when they were already connected."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.size[ra] < self.size[rb]:       # attach the smaller tree under the larger
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        self._count -= 1
        return True

    def connected(self, a: int, b: int) -> bool:
        return self.find(a) == self.find(b)

    def components(self) -> dict[int, list[int]]:
        """Every set, keyed by root. Used by the embed retry loop to report what was orphaned."""
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            groups.setdefault(self.find(i), []).append(i)
        return groups


def demo() -> None:
    d = DisjointSet(6)
    assert d.count == 6
    assert all(d.find(i) == i for i in range(6))

    # union reports whether it actually merged anything
    assert d.union(0, 1) is True
    assert d.union(0, 1) is False, "re-unioning a connected pair must report no change"
    assert d.count == 5
    assert d.connected(0, 1) and not d.connected(0, 2)

    # transitivity
    d.union(1, 2)
    assert d.connected(0, 2), "union must be transitive"
    assert d.count == 4

    # union by size: attaching a singleton to a big tree must not deepen it
    d2 = DisjointSet(5)
    d2.union(0, 1); d2.union(0, 2); d2.union(0, 3)   # 0 is the big root
    d2.union(4, 3)                                    # 4 attaches under 0, not the reverse
    assert d2.find(4) == 0, "the smaller tree must hang under the larger"

    # depth stays flat: chain n singletons together, then two full find passes
    n = 10_000
    d3 = DisjointSet(n)
    for i in range(n - 1):
        d3.union(i, i + 1)          # 0..n-1 ends as one set
    assert d3.count == 1

    def depth() -> int:
        worst = 0
        for i in range(n):
            h, cur = 0, i
            while d3.parent[cur] != cur:
                cur = d3.parent[cur]
                h += 1
            worst = max(worst, h)
        return worst

    d3.find(0)                       # touch one end
    after_one = depth()
    for i in range(0, n, 97):        # sparse second pass, enough to flatten
        d3.find(i)
    after_two = depth()
    assert after_two <= 2, f"path compression failed to flatten: depth {after_two}"
    assert after_two <= after_one, "compression must not deepen trees"

    # components() agrees with count, and names every element exactly once
    comps = d.components()
    assert len(comps) == d.count
    assert sum(len(v) for v in comps.values()) == 6

    print(f"OK  DisjointSet: {n} chained unions -> depth {after_one} then {after_two} after "
          f"compression, count={d.count}")


if __name__ == "__main__":
    demo()
