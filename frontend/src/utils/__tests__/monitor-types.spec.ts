import { describe, it, expect } from "vitest";
import { GEO_PLATFORMS } from "../monitor-types";

describe("GEO_PLATFORMS", () => {
  it("includes DeepSeek as an rpa platform", () => {
    const ds = GEO_PLATFORMS.find((p) => p.value === "deepseek");
    expect(ds).toBeTruthy();
    expect(ds?.mode).toBe("rpa");
  });
  it("keeps api platforms tagged api", () => {
    expect(GEO_PLATFORMS.find((p) => p.value === "tongyi")?.mode).toBe("api");
  });
});
