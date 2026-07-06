/**
 * 品牌型号页「参数分组」本体（素材库 V2 设计稿）。
 *
 * 设计决策（用户拍板 · 2026-07）：照设计稿的 6 个精选组渲染，而不是跟随
 * vault 的 7 个真实 H2 小节。后端 `/api/brand-memory/:model` 返回的 specs
 * 是**扁平** `{字段: SpecValue}`（小节分组在 parse_spec_table 里已被拍平），
 * 所以分组本体放在前端。
 *
 * 关键：真实 vault 字段名与设计稿标签有空格 / 全半角括号差异
 *   真实 `吸力(AW)` `最低噪音（dB）` `主机重量(kg)` `HEPA等级`
 *   设计 `吸力 (AW)` `最低噪音 (dB)` `主机重量 (kg)` `HEPA 等级`
 * → 匹配一律走 normKey（吃掉空格 + 全角括号→半角），展示用设计稿的清洗标签、
 *   取值用真实 SpecValue。未被本体覆盖且非占位的真实字段兜底进「其他」组，
 *   保证任何真实数据都不丢。
 */
import type { SpecValue } from "@/stores/materials";

export interface SpecRow {
  label: string;
  value: string;
  dim: boolean; // 未收集 / 占位 → 显示「—」、弱化配色
}
export interface SpecGroup {
  idx: number;
  title: string;
  rows: SpecRow[];
  filled: string; // "3 / 5"
}
export interface StatItem {
  label: string;
  value: string;
  dim: boolean;
}

/** 6 个精选组 —— 字段标签为设计稿清洗版；真实匹配走 normKey。 */
export const PARAM_GROUPS: { title: string; keys: string[] }[] = [
  { title: "基础信息", keys: ["价格", "产品链接", "产品尺寸", "产品类型", "认证检测"] },
  { title: "核心性能", keys: ["吸力 (AW)", "真空度 (Pa)", "电机功率", "电机转速", "入口风量"] },
  { title: "噪音表现", keys: ["最低噪音 (dB)", "标准档噪音", "强力档噪音", "超强档噪音", "清洁效果"] },
  { title: "续航与电池", keys: ["不同档位续航", "最长续航", "强力模式续航", "电池容量", "充电时长"] },
  { title: "刷头与整机", keys: ["尘杯容量", "主机重量 (kg)", "主地刷", "刷头配件", "刷头数量", "主刷头使用范围"] },
  { title: "过滤与其他", keys: ["HEPA 等级", "过滤系统", "核心部件可水洗", "实测", "适用场景", "特色功能"] },
];

/** 摘要卡 5 项 stat —— key 用规范化后能命中真实字段的形式。 */
const STATS: { key: string; label: string; unit?: string; money?: boolean }[] = [
  { key: "价格", label: "价格", money: true },
  { key: "吸力(AW)", label: "吸力", unit: "AW" },
  { key: "真空度(Pa)", label: "真空度", unit: "Pa" },
  { key: "最低噪音(dB)", label: "最低噪音", unit: "dB" },
  { key: "主机重量(kg)", label: "整机重量", unit: "kg" },
];

/** 吃掉空格 + 全角括号→半角 + 小写，跨「设计标签 vs 真实字段」匹配。 */
export function normKey(s: string): string {
  return s
    .replace(/\s+/g, "")
    .replace(/（/g, "(")
    .replace(/）/g, ")")
    .toLowerCase();
}

function specMap(specs: Record<string, SpecValue>): Map<string, SpecValue> {
  const map = new Map<string, SpecValue>();
  for (const k of Object.keys(specs)) map.set(normKey(k), specs[k]);
  return map;
}

/** 数字格式化：220.0 → "220"、1.5 → "1.5"（JS Number 无 int/float 之分，String 即可）。 */
function fnum(n: number): string {
  return String(n);
}

/**
 * 按 6 组本体把扁平 specs 组织成分组卡数据。
 * 进度（filled/total）只统计 6 组内的字段（与设计稿「参数 X / Y」语义一致）；
 * 「其他」兜底组仅用于展示真实的未覆盖字段，不计入进度分母。
 */
export function buildSpecGroups(specs: Record<string, SpecValue>): {
  groups: SpecGroup[];
  filled: number;
  total: number;
} {
  const map = specMap(specs);
  const used = new Set<string>();
  const groups: SpecGroup[] = [];
  let filled = 0;
  let total = 0;

  PARAM_GROUPS.forEach((g, idx) => {
    const rows: SpecRow[] = g.keys.map((label) => {
      const nk = normKey(label);
      used.add(nk);
      const spec = map.get(nk);
      const dim = !spec || spec.is_placeholder;
      total += 1;
      if (!dim) filled += 1;
      return { label, value: dim ? "—" : spec!.raw, dim };
    });
    const f = rows.filter((r) => !r.dim).length;
    groups.push({ idx, title: g.title, rows, filled: `${f} / ${g.keys.length}` });
  });

  // 其他：真实字段里未被本体覆盖且非占位的，兜底展示（真实数据零丢失）。
  const extra: SpecRow[] = [];
  for (const k of Object.keys(specs)) {
    if (used.has(normKey(k))) continue;
    const spec = specs[k];
    if (spec.is_placeholder) continue;
    extra.push({ label: k, value: spec.raw, dim: false });
  }
  if (extra.length) {
    groups.push({
      idx: PARAM_GROUPS.length,
      title: "其他",
      rows: extra,
      filled: `${extra.length} / ${extra.length}`,
    });
  }

  return { groups, filled, total };
}

/** 摘要卡 5 项 stat：优先用抽出的数字 + 设计单位，避免真实值 "70dB" 再拼 " dB" 双单位。 */
export function buildStats(specs: Record<string, SpecValue>): StatItem[] {
  const map = specMap(specs);
  return STATS.map((s) => {
    const spec = map.get(normKey(s.key));
    const dim = !spec || spec.is_placeholder;
    if (dim) return { label: s.label, value: "—", dim: true };
    let value: string;
    if (s.money) {
      value = spec!.numbers.length ? "¥" + fnum(spec!.numbers[0]) : spec!.raw;
    } else if (spec!.numbers.length) {
      value = fnum(spec!.numbers[0]) + (s.unit ? " " + s.unit : "");
    } else {
      value = spec!.raw;
    }
    return { label: s.label, value, dim: false };
  });
}

/**
 * 商品页链接：真实值已是完整 URL 时直接用；裸链接（像域名：含点、无空白）补 https://；
 * 否则视为描述文本而非链接，返回 null（避免设计稿无条件拼 https 造成 `https://某描述文本`
 * 这种打不开的死链，或 `https://https://`）。
 */
export function productHref(specs: Record<string, SpecValue>): string | null {
  const map = specMap(specs);
  const spec = map.get(normKey("产品链接"));
  if (!spec || spec.is_placeholder || !spec.raw.trim()) return null;
  const raw = spec.raw.trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  // 裸链接必须像域名：含点、无空白；否则是描述文本不是链接。
  if (/\s/.test(raw) || !raw.includes(".")) return null;
  return "https://" + raw;
}

/** 去掉型号里的品牌前缀：strip("CEWEYDS18","CEWEY") → "DS18"。 */
export function stripBrand(name: string, brand: string): string {
  return (name.startsWith(brand) ? name.slice(brand.length) : name) || name;
}
