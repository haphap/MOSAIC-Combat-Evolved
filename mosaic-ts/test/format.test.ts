import pc from "picocolors";
import { describe, expect, it } from "vitest";
import { displayWidth, pad } from "../src/cli/_format.js";

describe("displayWidth", () => {
  it("counts ASCII as 1 column each", () => {
    expect(displayWidth("abc")).toBe(3);
  });

  it("counts CJK as 2 columns each", () => {
    expect(displayWidth("波动率")).toBe(6); // 3 Han chars × 2
    expect(displayWidth("a波b")).toBe(4); // 1 + 2 + 1
  });

  it("ignores ANSI colour escapes", () => {
    expect(displayWidth(pc.green("abc"))).toBe(3);
    expect(displayWidth(pc.red("波动"))).toBe(4);
  });
});

describe("pad (§14 R-T2)", () => {
  it("pads ASCII to the target column width", () => {
    expect(pad("ab", 5)).toBe("ab   ");
  });

  it("pads by display width so CJK cells align", () => {
    // "波动率" is 6 columns → pad to 10 adds 4 spaces (naive .length would add 7).
    const out = pad("波动率", 10);
    expect(displayWidth(out)).toBe(10);
    expect(out).toBe("波动率    ");
  });

  it("does not truncate when content already exceeds width", () => {
    expect(pad("波动率分析", 4)).toBe("波动率分析");
  });

  it("accounts for ANSI when padding colourised cells", () => {
    const out = pad(pc.green("波动"), 8);
    expect(displayWidth(out)).toBe(8); // 4 visible + 4 spaces
  });
});
