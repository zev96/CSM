import { describe, it, expect } from "vitest";
import {
  uniqId,
  uniqueSearchTargetUrl,
  uniqueGeoTargetUrl,
} from "../taskTargetUrl";

describe("uniqId", () => {
  it("每次调用产出不同的值", () => {
    expect(uniqId()).not.toBe(uniqId());
  });
});

describe("uniqueSearchTargetUrl（baidu / zhihu_search）", () => {
  const BAIDU = "https://www.baidu.com/s?wd=";
  const ZHIHU = "https://www.zhihu.com/search?type=content&q=";

  it("同一首关键词建两个任务 → target_url 互不相同（不会撞 UNIQUE 键被覆盖）", () => {
    // 这是本次修复的核心回归用例：以前同首词派生出相同 target_url，
    // create_task 的 ON CONFLICT(type,target_url) DO UPDATE 会把先建的任务覆盖掉。
    const a = uniqueSearchTargetUrl(BAIDU, "扫地机器人", "");
    const b = uniqueSearchTargetUrl(BAIDU, "扫地机器人", "");
    expect(a).not.toBe(b);
  });

  it("仍是可点击的真实搜索 URL（保留 base + 编码后的关键词）", () => {
    const url = uniqueSearchTargetUrl(ZHIHU, "猫 砂", "");
    expect(url.startsWith(ZHIHU)).toBe(true);
    expect(url).toContain(encodeURIComponent("猫 砂"));
  });

  it("编辑模式（existing 非空）→ 沿用原 target_url，键不变", () => {
    const existing =
      "https://www.zhihu.com/search?type=content&q=x&_csm=fixed-key";
    expect(uniqueSearchTargetUrl(ZHIHU, "完全不同的关键词", existing)).toBe(
      existing,
    );
  });

  it("existing 为纯空白 → 视为新建并生成唯一键", () => {
    const url = uniqueSearchTargetUrl(BAIDU, "x", "   ");
    expect(url.startsWith(BAIDU)).toBe(true);
    expect(url).not.toBe("   ");
  });
});

describe("uniqueGeoTargetUrl（geo_query）", () => {
  it("同品牌建两个任务 → target_url 互不相同", () => {
    expect(uniqueGeoTargetUrl("希喂", "")).not.toBe(uniqueGeoTargetUrl("希喂", ""));
  });

  it("生成合成键格式 geo://<brand>/<uniq>", () => {
    expect(uniqueGeoTargetUrl("希喂", "")).toMatch(/^geo:\/\/希喂\//);
  });

  it("编辑模式（existing 非空）→ 沿用原 target_url", () => {
    expect(uniqueGeoTargetUrl("希喂", "geo://希喂/keep")).toBe("geo://希喂/keep");
  });
});
