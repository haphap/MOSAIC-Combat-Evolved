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
