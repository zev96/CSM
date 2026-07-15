/**
 * 品牌型号页参数展示(素材库 V3 · 产品线通用化,2026-07-14 spec)。
 *
 * 分组不再用前端硬编码本体(V2 的设计稿 6 组已废,用户拍板):后端 SpecValue
 * 自带 section(笔记真实 H2 小节名),按它分组、保持笔记顺序 —— vault 即真相源,
 * 任何产品线(吸尘器 7 节/净化器 5 节/未来新线)自动正确。
 *
 * 摘要卡是唯一保留的每线小配置(5 个头条数字的展示偏好):已知产品线精选,
 * 未知产品线兜底「价格 + 前 4 个短数值字段」;缺配置只影响观感不影响可用。
 */
import type { SpecValue } from "@/stores/materials";

export interface SpecRow {
  label: string;
  value: string;
  dim: boolean; // 占位/未收集 → 显示「—」、弱化配色
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

interface StatSpec {
  key: string;      // 规范化后命中真实字段
  label: string;
  unit?: string;    // 指定时用 numbers[0]+unit(避免 "70dB"+dB 双单位)
  money?: boolean;  // ¥ 前缀
}

/** 已知产品线的摘要卡精选;未知线走 genericStats 兜底。 */
const STATS_BY_LINE: Record<string, StatSpec[]> = {
  吸尘器: [
    { key: "价格", label: "价格", money: true },
    { key: "吸力(AW)", label: "吸力", unit: "AW" },
    { key: "真空度(Pa)", label: "真空度", unit: "Pa" },
    { key: "最低噪音(dB)", label: "最低噪音", unit: "dB" },
    { key: "主机重量(kg)", label: "整机重量", unit: "kg" },
  ],
  空气净化器: [
    { key: "价格", label: "价格", money: true },
    { key: "颗粒物CADR", label: "颗粒物CADR" },
    { key: "甲醛CADR", label: "甲醛CADR" },
    { key: "最低档声功率级噪音", label: "噪音" },
    { key: "适用面积", label: "适用面积" },
  ],
};

/** 吃掉空格 + 全角括号→半角 + 小写,跨「配置 key vs 真实字段」匹配。 */
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
 * 按 SpecValue.section 分组(笔记真实 H2 小节),保持笔记原始顺序。
 * 进度:分母 = 真实字段总数,分子 = 非占位字段数。空 specs → 空 groups。
 */
export function buildSpecGroups(specs: Record<string, SpecValue>): {
  groups: SpecGroup[];
  filled: number;
  total: number;
} {
  const groups: SpecGroup[] = [];
  const byTitle = new Map<string, SpecGroup>();
  let filled = 0;
  let total = 0;

  for (const k of Object.keys(specs)) {
    const s = specs[k];
    const title = s.section || "参数"; // 旧缓存/无小节笔记兜底
    let g = byTitle.get(title);
    if (!g) {
      g = { idx: groups.length, title, rows: [], filled: "" };
      byTitle.set(title, g);
      groups.push(g);
    }
    const dim = s.is_placeholder;
    total += 1;
    if (!dim) filled += 1;
    g.rows.push({ label: k, value: dim ? "—" : s.raw, dim });
  }
  for (const g of groups) {
    g.filled = `${g.rows.filter((r) => !r.dim).length} / ${g.rows.length}`;
  }
  return { groups, filled, total };
}

function curatedStats(specs: Record<string, SpecValue>, curated: StatSpec[]): StatItem[] {
  const map = specMap(specs);
  return curated.map((s) => {
    const spec = map.get(normKey(s.key));
    const dim = !spec || spec.is_placeholder;
    if (dim) return { label: s.label, value: "—", dim: true };
    let value: string;
    if (s.money) {
      value = spec!.numbers.length ? "¥" + fnum(spec!.numbers[0]) : spec!.raw;
    } else if (s.unit && spec!.numbers.length) {
      value = fnum(spec!.numbers[0]) + " " + s.unit;
    } else {
      value = spec!.raw; // 无单位配置 → raw 原文(区间/复合单位不失真)
    }
    return { label: s.label, value, dim: false };
  });
}

function genericStats(specs: Record<string, SpecValue>): StatItem[] {
  const out: StatItem[] = [];
  const price = specMap(specs).get(normKey("价格"));
  if (price && !price.is_placeholder) {
    out.push({
      label: "价格",
      value: price.numbers.length ? "¥" + fnum(price.numbers[0]) : price.raw,
      dim: false,
    });
  }
  for (const k of Object.keys(specs)) {
    if (out.length >= 5) break;
    if (normKey(k) === normKey("价格") || k.includes("链接")) continue;
    const s = specs[k];
    if (s.is_placeholder || !s.numbers.length || s.raw.length > 12) continue;
    out.push({ label: k, value: s.raw, dim: false });
  }
  return out;
}

/** 摘要卡:已知产品线精选(恒 5 项,缺失显「—」);未知线兜底(有几项显几项)。 */
export function buildStats(
  specs: Record<string, SpecValue>,
  productLine: string,
): StatItem[] {
  const curated = STATS_BY_LINE[productLine];
  if (curated) return curatedStats(specs, curated);
  return genericStats(specs);
}

/**
 * 商品页链接：真实值已是完整 URL 时直接用；裸链接（像域名：含点、无空白）补 https://；
 * 否则视为描述文本而非链接，返回 null（避免拼出打不开的死链或 `https://https://`）。
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
