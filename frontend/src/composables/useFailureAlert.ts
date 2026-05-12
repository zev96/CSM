/**
 * 全局失败弹窗 —— 比 toast 更重的语义。
 *
 * 起因：文章生成失败时，老流程是先 router.push 到创作区，再在创作区
 * 顶部摆一条红色 banner。问题是用户已经被推进了一个"半成品页面"，
 * 一眼看不清是失败还是部分成功，还得自己点返回。新流程是：失败一旦
 * 检测到就 push 回首页 + 弹这个模态，强调"这次没成"，并提供两个出口
 * （关闭 / 重试）。
 *
 * 单例 + Promise 命令式 API，沿用 useConfirm.ts 的形态：
 *
 *   const choice = await failureAlert({ title, message, detail });
 *   // choice: "close" | "retry"
 *
 * 不需要回调订阅模式，因为这个 alert 在调用栈里就是一个 await 点 ——
 * 调起 alert 的代码自己处理 retry 分支更自然。
 */
import { reactive } from "vue";

interface FailureRequest {
  title: string;
  message: string;
  detail: string;
  /** 是否显示「重试」按钮 —— 没传 onRetry-able 场景就只显示关闭。 */
  retryable: boolean;
  resolve: (v: "close" | "retry") => void;
}

interface FailureState {
  open: boolean;
  title: string;
  message: string;
  detail: string;
  retryable: boolean;
}

export const failureState = reactive<FailureState>({
  open: false,
  title: "操作失败",
  message: "",
  detail: "",
  retryable: false,
});

const queue: FailureRequest[] = [];
let current: FailureRequest | null = null;

function showNext() {
  if (current || queue.length === 0) return;
  current = queue.shift()!;
  failureState.title = current.title;
  failureState.message = current.message;
  failureState.detail = current.detail;
  failureState.retryable = current.retryable;
  failureState.open = true;
}

/** FailureAlertModal 点按钮后调，传 "close" 或 "retry"。 */
export function resolveFailure(value: "close" | "retry") {
  if (!current) return;
  const c = current;
  current = null;
  failureState.open = false;
  c.resolve(value);
  Promise.resolve().then(showNext);
}

export interface FailureOptions {
  title?: string;
  message: string;
  /** 折叠的二级技术细节（异常字符串），用 `<pre>` 等宽渲染。 */
  detail?: string;
  retryable?: boolean;
}

export function failureAlert(
  opts: FailureOptions,
): Promise<"close" | "retry"> {
  return new Promise<"close" | "retry">((resolve) => {
    queue.push({
      title: opts.title ?? "操作失败",
      message: opts.message,
      detail: opts.detail ?? "",
      retryable: opts.retryable ?? false,
      resolve,
    });
    showNext();
  });
}
