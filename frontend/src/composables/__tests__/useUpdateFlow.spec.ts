import { describe, it, expect, beforeEach } from "vitest";
import {
  getSkippedVersion,
  markVersionSkipped,
  shouldAutoPrompt,
} from "../useUpdateFlow";

beforeEach(() => {
  localStorage.clear();
});

describe("skip-version persistence", () => {
  it("returns empty string when nothing skipped", () => {
    expect(getSkippedVersion()).toBe("");
  });
  it("persists then reads back a skipped version", () => {
    markVersionSkipped("1.2.3");
    expect(getSkippedVersion()).toBe("1.2.3");
  });
  it("overwrites a previously skipped version", () => {
    markVersionSkipped("1.2.3");
    markVersionSkipped("1.3.0");
    expect(getSkippedVersion()).toBe("1.3.0");
  });
});

describe("shouldAutoPrompt", () => {
  it("prompts when latest differs from skipped", () => {
    expect(shouldAutoPrompt("1.2.4", "1.2.3")).toBe(true);
  });
  it("suppresses when latest equals skipped", () => {
    expect(shouldAutoPrompt("1.2.3", "1.2.3")).toBe(false);
  });
  it("prompts when nothing is skipped", () => {
    expect(shouldAutoPrompt("1.2.3", "")).toBe(true);
  });
});
