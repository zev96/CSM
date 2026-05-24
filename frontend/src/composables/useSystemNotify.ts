import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification"

/**
 * Tauri 系统通知封装。
 *
 * native mode（方案 D）用：
 *   - 等关 Chrome
 *   - 监控完成
 *   - 需要人工解验证码
 *
 * 调用方传 title + body，本封装处理权限请求 + 静默 fallback（权限拒绝时不抛）。
 */
export function useSystemNotify() {
  async function notify(title: string, body: string): Promise<void> {
    let granted = await isPermissionGranted()
    if (!granted) {
      const result = await requestPermission()
      granted = result === "granted"
    }
    if (granted) {
      await sendNotification({ title, body })
    }
  }
  return { notify }
}
