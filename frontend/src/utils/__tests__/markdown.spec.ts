import { describe, it, expect } from "vitest";
import { ensureTitle, leadingTitle, replaceLeadingTitle, mdToHtml } from "@/utils/markdown";

describe("ensureTitle —— 与后端 ensure_title 同口径", () => {
  it("没有标题就补一个", () => {
    expect(ensureTitle("## 一、品牌分析\n正文", "榜单")).toBe("# 榜单\n\n## 一、品牌分析\n正文");
  });
  it("已经有 H1 就原样返回（幂等）—— 否则 txt 导出会出双标题", () => {
    expect(ensureTitle("# 榜单\n\n正文", "另一个")).toBe("# 榜单\n\n正文");
  });
  it("跳过前导空行，与后端一致（旧 withTitle 用 startsWith 判不到）", () => {
    expect(ensureTitle("\n\n# 榜单\n正文", "另一个")).toBe("\n\n# 榜单\n正文");
  });
  it("H2 是章节标题不是文章标题", () => {
    expect(ensureTitle("## 章节\n正文", "榜单")).toBe("# 榜单\n\n## 章节\n正文");
  });
  it("多行标题压成单行 —— H1 是单行结构", () => {
    expect(ensureTitle("正文", " 多行\n标题 ")).toBe("# 多行 标题\n\n正文");
  });
  it("没标题可补时不动正文", () => {
    expect(ensureTitle("正文", "   ")).toBe("正文");
  });
});

describe("replaceLeadingTitle —— 「换标题」要能覆盖已内嵌的 H1", () => {
  it("正文里内嵌了 H1 就就地改写", () => {
    expect(replaceLeadingTitle("# 旧标题\n\n正文", "新标题")).toBe("# 新标题\n\n正文");
  });
  it("正文里没有 H1 就原样返回（标题另存在 store 字段里）", () => {
    expect(replaceLeadingTitle("## 章节\n正文", "新标题")).toBe("## 章节\n正文");
  });
  it("跳过前导空行", () => {
    expect(replaceLeadingTitle("\n# 旧\n正文", "新")).toBe("\n# 新\n正文");
  });
  it("空正文/空标题不炸", () => {
    expect(replaceLeadingTitle("", "x")).toBe("");
    expect(replaceLeadingTitle("# 旧", "")).toBe("# 旧");
  });
  it("leadingTitle 只认 H1", () => {
    expect(leadingTitle("# 甲\n正文")).toBe("甲");
    expect(leadingTitle("## 甲\n正文")).toBe("");
  });
});

describe("mdToHtml —— v-html 的安全边界", () => {
  it("标签一律转义，产出只有 p/br/h1-6/strong 且不含属性", () => {
    const html = mdToHtml('<img src=x onerror="alert(1)">\n\n## <script>bad</script>');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<script");
    expect(html).toContain("&lt;img");
    expect(html).toContain("<h2>");
  });
  it("加粗里嵌标签也先转义", () => {
    expect(mdToHtml("**<b>x</b>**")).toBe("<p><strong>&lt;b&gt;x&lt;/b&gt;</strong></p>");
  });
});
