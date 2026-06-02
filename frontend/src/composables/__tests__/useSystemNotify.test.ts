import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { useSystemNotify } from "../useSystemNotify"

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}))

import * as notif from "@tauri-apps/plugin-notification"

// notify 现在先探测 Tauri 在场（window.__TAURI_INTERNALS__）才走 IPC，
// 否则静默 no-op。jsdom 默认没有这个全局 —— 大多数用例需要先打开它。
function withTauri(): void {
  // @ts-expect-error — ambient Tauri global not in our types
  window.__TAURI_INTERNALS__ = { invoke: vi.fn() }
}
function withoutTauri(): void {
  // @ts-expect-error — ambient Tauri global not in our types
  delete window.__TAURI_INTERNALS__
  // @ts-expect-error — ambient Tauri global not in our types
  delete window.__TAURI__
}

describe("useSystemNotify", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    withTauri()
  })
  afterEach(() => {
    withoutTauri()
  })

  it("sends notification when permission already granted", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(true)
    const { notify } = useSystemNotify()
    await notify("Title", "Body")
    expect(notif.sendNotification).toHaveBeenCalledWith({ title: "Title", body: "Body" })
    expect(notif.requestPermission).not.toHaveBeenCalled()
  })

  it("requests permission then sends when not granted", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(false)
    vi.mocked(notif.requestPermission).mockResolvedValue("granted")
    const { notify } = useSystemNotify()
    await notify("T", "B")
    expect(notif.requestPermission).toHaveBeenCalled()
    expect(notif.sendNotification).toHaveBeenCalledWith({ title: "T", body: "B" })
  })

  it("silently skips when permission denied", async () => {
    vi.mocked(notif.isPermissionGranted).mockResolvedValue(false)
    vi.mocked(notif.requestPermission).mockResolvedValue("denied")
    const { notify } = useSystemNotify()
    await notify("T", "B")
    expect(notif.sendNotification).not.toHaveBeenCalled()
  })

  it("silently no-ops (no IPC call) when not running inside Tauri", async () => {
    // 浏览器 dev：window.__TAURI_INTERNALS__ 不存在 —— notify 应直接返回，
    // 绝不触碰 @tauri-apps/plugin-notification 的任何 API（否则会抛
    // TypeError: Cannot read properties of undefined reading 'invoke'）。
    withoutTauri()
    const { notify } = useSystemNotify()
    await expect(notify("T", "B")).resolves.toBeUndefined()
    expect(notif.isPermissionGranted).not.toHaveBeenCalled()
    expect(notif.requestPermission).not.toHaveBeenCalled()
    expect(notif.sendNotification).not.toHaveBeenCalled()
  })
})
