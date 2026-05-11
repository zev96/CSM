import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import router from "./router";
import { useSidecar } from "./stores/sidecar";

import "./style.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);

// ── 全局错误监控 ────────────────────────────────────────────────────────────
// 切路由空白页这种 bug 很难追，因为 Vue 的 errorHandler 默认会"吞掉"渲染
// 函数里的同步异常然后跳过该组件，外加 onMounted 里的 await 链条容易混入
// unhandledrejection。下面三层都接住，错误会同时打到 console（带完整堆栈）
// 和右下角弹层（用 alert 是简单粗暴但显眼，不会被 Vue 的虚拟 DOM 吃掉）。
//
// 装好后下次再出空白页，console 一定会有红色错误条 + 弹层提示具体哪一行。
function reportError(label: string, err: unknown, info?: unknown) {
  // eslint-disable-next-line no-console
  console.error(`[CSM-error] ${label}`, err, info ?? "");
  // 在 dev 环境用 alert 强制弹一次，确保用户能看到 —— 不依赖 Vue 渲染。
  // 生产环境可以换成 toast，但目前 toast 也走 Vue 渲染，挂了的时候不可信。
  if (import.meta.env.DEV) {
    const msg =
      err instanceof Error
        ? `${err.name}: ${err.message}\n\n${err.stack ?? ""}`
        : String(err);
    // setTimeout 让 alert 不阻塞当前 microtask，避免和 Vue 调度打架
    setTimeout(() => {
      // eslint-disable-next-line no-alert
      alert(`[${label}]\n${msg}`);
    }, 0);
  }
}

// 1. Vue 渲染函数 / 生命周期 / watcher 回调里的同步异常（包括从 await 拆开
//    的 then 链）—— Vue 把它们集中喂到 errorHandler。
app.config.errorHandler = (err, _instance, info) => {
  reportError(`Vue:${info}`, err);
};

// 2. <template> 里的运行时警告 —— 不是致命错误，但 reading 'undefined.x'
//    这种通常会先打 warn 再抛，捕获 warn 能让我们更早发现。
app.config.warnHandler = (msg, _instance, trace) => {
  // 仅 dev 环境处理，避免生产里冒出 alert
  if (import.meta.env.DEV && /undefined|null|cannot read/i.test(msg)) {
    reportError("Vue:warn", new Error(msg), trace);
  }
};

// 3. 全局未捕获错误（同步异常没被任何 try/catch 接住）
window.addEventListener("error", (ev) => {
  reportError("window:error", ev.error ?? ev.message, ev.filename);
});

// 4. 未捕获的 promise rejection（async/await 链路上漏了 catch）—— 这个
//    最重要，绝大多数视图在 onMounted 里 await sidecar，async 函数里抛
//    的错没 try/catch 就走这里。
window.addEventListener("unhandledrejection", (ev) => {
  reportError("unhandledrejection", ev.reason);
});

// Boot the sidecar bridge before mounting so the first view can already
// hit /api/* without a flash of "loading…". If it fails (e.g. running in
// the browser without Tauri) the store flips into dev-fallback mode and
// uses VITE_SIDECAR_URL — no app crash, just a warning in console.
const sidecar = useSidecar();
sidecar.bootstrap().catch((err) => {
  console.error("[CSM] sidecar bootstrap failed:", err);
});

app.mount("#app");
