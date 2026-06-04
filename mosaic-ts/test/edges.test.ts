import { describe, expect, it } from "vitest";
import { chainEdges, serialEdges } from "../src/graph/_edges.js";

describe("chainEdges", () => {
  it("adds each edge by side effect and returns the same graph", () => {
    const calls: Array<[string, string]> = [];
    const fake = {
      addEdge(start: string, end: string) {
        calls.push([start, end]);
        return this;
      },
    };

    const returned = chainEdges(fake, [
      ["__start__", "a"],
      ["a", "b"],
      ["b", "__end__"],
    ]);

    expect(returned).toBe(fake); // returns the same instance (mutated in place)
    expect(calls).toEqual([
      ["__start__", "a"],
      ["a", "b"],
      ["b", "__end__"],
    ]);
  });

  it("no-ops on an empty edge list", () => {
    let n = 0;
    const fake = {
      addEdge() {
        n += 1;
        return this;
      },
    };
    chainEdges(fake, []);
    expect(n).toBe(0);
  });

  it("derives serial edge pairs from a canonical node list", () => {
    expect(serialEdges(["__start__", "a", "b", "__end__"])).toEqual([
      ["__start__", "a"],
      ["a", "b"],
      ["b", "__end__"],
    ]);
  });
});
