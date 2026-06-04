/**
 * Typed helper for accumulating LangGraph edges in a loop (Plan §14 R-T1).
 *
 * LangGraph's ``StateGraph`` fluent API narrows the node-name type parameter on
 * every ``.addNode()`` / ``.addEdge()`` call, so the old pattern —
 * ``let graph: any = new StateGraph(...)`` then reassigning ``graph =
 * graph.addEdge(...)`` in a loop — had to erase the type to ``any`` to compile.
 *
 * ``StateGraph`` mutates in place and returns ``this``, so edges can be added by
 * **side effect** without reassigning. ``chainEdges`` does exactly that, deriving
 * the accepted edge endpoint type from the graph's *own* ``addEdge`` signature
 * (via ``Parameters<G["addEdge"]>``) so there is no ``any`` and no hand-rebuilt
 * node-name union to drift from LangGraph's real types.
 *
 * ASSUMPTION (pinned to ``@langchain/langgraph`` 1.3.x): ``addEdge`` mutates the
 * builder in place — its return value is intentionally ignored here. If a future
 * LangGraph made the builder immutable (returning a new instance), edges added
 * via ``chainEdges`` would be silently dropped; the unit test's fake mirrors the
 * current behavior and would NOT catch that. The real safety net is the
 * layer/daily-cycle integration tests, which compile + invoke the graphs (a
 * missing edge breaks execution) — re-verify those on any LangGraph upgrade.
 */

/** Anything with an ``addEdge(start, end)`` method (StateGraph after addNode). */
interface EdgeAddable {
  addEdge(start: never, end: never): unknown;
}

/** The ``[start, end]`` endpoint pair ``graph.addEdge`` accepts. */
type EdgeOf<G extends EdgeAddable> = readonly [
  Parameters<G["addEdge"]>[0],
  Parameters<G["addEdge"]>[1],
];

type SerialEdgePairs<Nodes extends readonly string[]> = Nodes extends readonly [
  infer From extends string,
  infer To extends string,
  ...infer Rest extends string[],
]
  ? readonly [readonly [From, To], ...SerialEdgePairs<readonly [To, ...Rest]>]
  : readonly [];

/**
 * Add each ``[from, to]`` edge to ``graph`` by side effect. Returns ``graph`` so
 * call sites can still ``return chainEdges(g, edges).compile()`` if desired.
 */
export function chainEdges<G extends EdgeAddable>(graph: G, edges: ReadonlyArray<EdgeOf<G>>): G {
  for (const [from, to] of edges) {
    (graph.addEdge as (start: unknown, end: unknown) => unknown)(from, to);
  }
  return graph;
}

/** Build consecutive ``[from, to]`` edge pairs from a canonical serial node list. */
export function serialEdges<const Nodes extends readonly [string, string, ...string[]]>(
  nodes: Nodes,
): SerialEdgePairs<Nodes> {
  const edges: Array<readonly [string, string]> = [];
  let previous = nodes[0];
  for (const next of nodes.slice(1)) {
    edges.push([previous, next]);
    previous = next;
  }
  return edges as unknown as SerialEdgePairs<Nodes>;
}
