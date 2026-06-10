/**
 * 进度 → 剩余时间估算（纯前端，后端不发 ETA）。
 *
 * 每个 key（托盘卡片）维护一条进度速率的 EMA（α=0.3）；
 * eta = (1 - p) / rate。显示门槛：≥2 个样本且 p ≥ 5%，
 * 否则返回 null（UI 不显示，避免冷启动数字乱跳）。
 * 进度回退视为同 key 被新一轮任务复用 → 重置。
 *
 * `now` 由调用方传入（生产传 Date.now()），测试可注入假时钟。
 */
const EMA_ALPHA = 0.3;
const MIN_PROGRESS = 0.05;

interface Sample {
  p: number;
  t: number;
  rate: number | null; // progress per ms
  n: number;
}

export class EtaEstimator {
  private samples = new Map<string, Sample>();

  observe(key: string, p: number, now: number): string | null {
    const prev = this.samples.get(key);
    if (!prev || p < prev.p) {
      this.samples.set(key, { p, t: now, rate: null, n: 1 });
      return null;
    }
    if (p > prev.p && now > prev.t) {
      const inst = (p - prev.p) / (now - prev.t);
      const rate = prev.rate == null ? inst : EMA_ALPHA * inst + (1 - EMA_ALPHA) * prev.rate;
      this.samples.set(key, { p, t: now, rate, n: prev.n + 1 });
    }
    const cur = this.samples.get(key)!;
    if (cur.n < 2 || cur.rate == null || cur.rate <= 0 || p < MIN_PROGRESS) return null;
    const remainMs = (1 - p) / cur.rate;
    if (remainMs < 60_000) return "不到 1 分钟";
    return `约 ${Math.round(remainMs / 60_000)} 分钟`;
  }

  /** 任务结束后释放，防 Map 无界增长。 */
  drop(key: string): void {
    this.samples.delete(key);
  }
}
