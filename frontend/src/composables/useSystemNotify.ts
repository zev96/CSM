import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification"

/**
 * Tauri 运行环境探测 —— 跟 stores/sidecar.ts / usePathPicker.ts 同款：
 * Tauri 2 注入 ``window.__TAURI_INTERNALS__``（老变体用 ``__TAURI__``）。
 * 纯浏览器 dev（``npm run dev`` 不走 Tauri shell）下两者都不存在。
 */
function isTauri(): boolean {
  if (typeof window === "undefined") return false
  // @ts-expect-error — ambient Tauri global not in our types
  return Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__)
}

/**
 * Tauri 系统通知封装。
 *
 * native mode（方案 D）用：
 *   - 等关 Chrome
 *   - 监控完成
 *   - 需要人工解验证码
 *
 * 调用方传 title + body，本封装处理权限请求 + 静默 fallback。
 * 静默降级两种情形：
 *   1) 不在 Tauri 里（浏览器 dev）—— ``@tauri-apps/plugin-notification``
 *      的 API 内部走 IPC（``window.__TAURI_INTERNALS__.invoke``），不在
 *      Tauri shell 下读 ``invoke`` 会抛 ``TypeError: Cannot read properties
 *      of undefined``。先探测 Tauri 在场，否则直接 no-op。
 *   2) 权限被拒 —— 不抛，安静跳过 sendNotification。
 * 整段再裹 try/catch 防守，任何意外都不冒泡打断调用方业务。
 */
export function useSystemNotify() {
  async function notify(title: string, body: string): Promise<void> {
    // 浏览器 dev 无 Tauri IPC —— 系统通知不可用，安静跳过。
    if (!isTauri()) return
    try {
      let granted = await isPermissionGranted()
      if (!granted) {
        const result = await requestPermission()
        granted = result === "granted"
      }
      if (granted) {
        await sendNotification({ title, body })
      }
    } catch {
      // IPC 尚未就绪 / 插件不可用 / 权限交互异常 —— 通知本就是 best-effort，
      // 任何失败都静默降级，不打断调用方（等关 Chrome / 监控完成等流程）。
    }
  }
  return { notify }
}
