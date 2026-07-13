/**
 * 断点 banner 分类 —— 把后端断点结果的 ``captcha_signal_layer`` 映射成三类 UI 处理。
 *
 * 断点结果（status="risk_control"）由两条路产生，共用同一 metric 形态、只有 layer
 * 不同（见 monitor_loop.py 的 _build_baidu_breakpoint）：
 *  - 风控中断：layer = signal.layer（auth / dom / text / …）
 *  - R2 崩溃中断：layer = 'interrupted'（程序退出/崩溃/硬杀恢复，不是反爬）
 *
 * 分类集中一处，避免 banner 模板里散落字符串比较。
 */
export type BreakpointKind = "auth" | "interrupted" | "risk";

export function breakpointKind(layer: string | null | undefined): BreakpointKind {
  if (layer === "auth") return "auth";
  if (layer === "interrupted") return "interrupted";
  return "risk";
}
