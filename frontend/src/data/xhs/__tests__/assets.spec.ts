import { describe, it, expect } from "vitest";
import {
  TEMPLATES, TEMPLATE_CATEGORIES, THEMES, EMOJI,
  TITLE_CATEGORIES, COPY_GROUPS, TOPIC_GROUPS, DECORATION_GROUPS,
  findTheme,
} from "@/data/xhs/assets";

describe("xhs 起步素材完整性", () => {
  it("模板：非空、id 唯一、字段齐全", () => {
    expect(TEMPLATES.length).toBeGreaterThan(0);
    const ids = TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of TEMPLATES) {
      expect(t.category).toBeTruthy();
      expect(t.name).toBeTruthy();
      expect(t.title).toBeTruthy();
      expect(typeof t.body).toBe("string");
      expect(Array.isArray(t.topics)).toBe(true);
    }
  });

  it("模板分类列表由模板去重得到、非空、无重复", () => {
    expect(TEMPLATE_CATEGORIES.length).toBeGreaterThan(0);
    expect(new Set(TEMPLATE_CATEGORIES).size).toBe(TEMPLATE_CATEGORIES.length);
    for (const c of TEMPLATE_CATEGORIES) {
      expect(TEMPLATES.some((t) => t.category === c)).toBe(true);
    }
  });

  it("主题：非空、id 唯一、ordered 合法、符号齐全、findTheme 命中", () => {
    expect(THEMES.length).toBeGreaterThan(0);
    const ids = THEMES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of THEMES) {
      expect(["emoji", "circle", "superscript"]).toContain(t.ordered);
      expect(t.heading).toBeTruthy();
      expect(t.bullet).toBeTruthy();
      expect(t.divider).toBeTruthy();
    }
    expect(findTheme(THEMES[0].id)?.id).toBe(THEMES[0].id);
    expect(findTheme(null)).toBeNull();
    expect(findTheme("不存在的id")).toBeNull();
  });

  it("表情：三段都非空，每个 emoji 分组有内容，代码以 [ 开头", () => {
    expect(EMOJI.curatedGroups.length).toBeGreaterThan(0);
    expect(EMOJI.unicodeGroups.length).toBeGreaterThan(0);
    expect(EMOJI.xhsCodes.length).toBeGreaterThan(0);
    for (const g of [...EMOJI.curatedGroups, ...EMOJI.unicodeGroups]) {
      expect(g.key).toBeTruthy();
      expect(g.name).toBeTruthy();
      expect(g.emojis.length).toBeGreaterThan(0);
    }
    for (const c of EMOJI.xhsCodes) {
      expect(c.code.startsWith("[")).toBe(true);
      expect(c.label).toBeTruthy();
    }
  });

  it("标题/文案/话题/装饰：分组非空且每组有条目", () => {
    expect(TITLE_CATEGORIES.length).toBeGreaterThan(0);
    expect(COPY_GROUPS.length).toBeGreaterThan(0);
    expect(TOPIC_GROUPS.length).toBeGreaterThan(0);
    expect(DECORATION_GROUPS.length).toBeGreaterThan(0);
    for (const c of TITLE_CATEGORIES) expect(c.items.length).toBeGreaterThan(0);
    for (const g of COPY_GROUPS) expect(g.items.length).toBeGreaterThan(0);
    for (const g of TOPIC_GROUPS) expect(g.tags.length).toBeGreaterThan(0);
    for (const g of DECORATION_GROUPS) expect(g.items.length).toBeGreaterThan(0);
  });
});
