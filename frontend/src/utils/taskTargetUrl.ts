/**
 * 监测任务 target_url 唯一化辅助。
 *
 * monitor_tasks 表有 `UNIQUE(type, target_url)`，且 `create_task` 用
 * `INSERT ... ON CONFLICT(type, target_url) DO UPDATE` —— 新建任务若 (type, target_url)
 * 撞上已有任务会 **UPDATE 覆盖**原任务（数据丢失）。baidu / zhihu_search / geo_query 的
 * adapter 都用 `config`（关键词/品牌）采集、并不请求 target_url，所以 target_url 仅作
 * UNIQUE 键。但 baidu / zhihu_search 的 target_url 同时被 UI 渲染成「点开真实搜索页」的
 * 链接（如 ZhihuSearchModule「知乎搜索页 ↗」），故不能像 GEO 那样用纯合成 `geo://`；
 * 改为「真实搜索 URL + 无害唯一参数 `_csm`」——既可点击打开真实搜索、又每任务唯一。
 * 编辑时沿用原 target_url（update 按 id、键不变，不再撞键）。
 */

/** 每次调用产出一个唯一 id（优先 crypto.randomUUID，降级时间戳+随机串）。 */
export function uniqId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

/**
 * baidu / zhihu_search 等「搜索类」任务的 target_url：保留可点击的真实搜索 URL，
 * 再追加无害唯一参数 `_csm` 确保每任务唯一。
 * @param baseWithQuery 以参数前缀结尾的基址，如 `https://www.baidu.com/s?wd=`
 * @param keyword       第一个关键词（搜索词）
 * @param existing      编辑模式传入原 target_url；非空则沿用（按 id 更新、键不变）
 */
export function uniqueSearchTargetUrl(
  baseWithQuery: string,
  keyword: string,
  existing = "",
): string {
  const e = existing.trim();
  if (e) return e;
  return `${baseWithQuery}${encodeURIComponent(keyword)}&_csm=${uniqId()}`;
}

/** geo_query 任务的 target_url：纯合成 UNIQUE 键（target_url 不展示、不被 adapter 请求）。 */
export function uniqueGeoTargetUrl(brand: string, existing = ""): string {
  const e = existing.trim();
  if (e) return e;
  return `geo://${brand}/${uniqId()}`;
}
