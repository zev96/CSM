import { describe, it, expect } from "vitest";

import type { CreationRecordRef } from "@/api/client";
import { buildRegenerateQuery, parseAngleJson } from "@/utils/regenerateQuery";

function rec(over: Partial<CreationRecordRef>): CreationRecordRef {
  return {
    keyword: "无线吸尘器", template_id: "tpl-a", title: "标题",
    angle_json: null, skill_chain_json: null, mode: "normal",
    models_json: null, contract_mode: null, ...over,
  };
}

describe("buildRegenerateQuery — §7.3 重生成 query 必须对齐 ArticleView 读取", () => {
  it("常规：keyword/template_id/skill_chain/audience/sellpoints/tone/title/contract 全对齐", () => {
    expect(buildRegenerateQuery(rec({
      angle_json: '{"audience":"铲屎官","sellpoints":["防缠绕","大吸力"],"tone":"口语"}',
      skill_chain_json: '["人设","去味"]', contract_mode: "aggressive",
    }))).toEqual({
      ok: true,
      query: {
        keyword: "无线吸尘器", title: "标题", template_id: "tpl-a",
        skill_chain: "人设,去味", contract: "aggressive",
        audience: "铲屎官", sellpoints: "防缠绕,大吸力", tone: "口语",
      },
    });
  });

  it("常规最简：只有 keyword（空 angle/chain/契约不入 query = 今天行为）", () => {
    expect(buildRegenerateQuery(rec({ template_id: null, title: null }))).toEqual({
      ok: true, query: { keyword: "无线吸尘器" },
    });
  });

  it("横评：mode=comparison + models + tone（从 angle_json）+ skill_chain + contract，不带 template_id", () => {
    expect(buildRegenerateQuery(rec({
      mode: "comparison", template_id: "__comparison__",
      models_json: '["戴森V12","希喂C1","小米G9"]',
      angle_json: '{"tone":"专业"}', skill_chain_json: '["人设"]', contract_mode: "conservative",
    }))).toEqual({
      ok: true,
      query: {
        keyword: "无线吸尘器", title: "标题", mode: "comparison",
        models: "戴森V12,希喂C1,小米G9", tone: "专业",
        skill_chain: "人设", contract: "conservative",
      },
    });
  });

  it("横评型号 <2 → error（对齐 ArticleView 的 ≥2 守卫）", () => {
    expect(buildRegenerateQuery(rec({ mode: "comparison", models_json: '["只有一个"]' })))
      .toEqual({ ok: false, error: expect.stringContaining("型号不足") });
  });

  it("坏 angle_json / models_json 不崩，facet 忽略", () => {
    expect(buildRegenerateQuery(rec({ angle_json: "not json", template_id: null, title: null })))
      .toEqual({ ok: true, query: { keyword: "无线吸尘器" } });
  });

  it("parseAngleJson 容错：非对象/数组/标量/null → null", () => {
    expect(parseAngleJson("[1,2]")).toBeNull();
    expect(parseAngleJson("123")).toBeNull();
    expect(parseAngleJson("bad")).toBeNull();
    expect(parseAngleJson(null)).toBeNull();
  });
});
