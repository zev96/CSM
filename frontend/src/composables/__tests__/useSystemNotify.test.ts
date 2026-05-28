import { describe, it, expect, vi, beforeEach } from "vitest"
import { useSystemNotify } from "../useSystemNotify"

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted: vi.fn(),
  requestPermission: vi.fn(),
  sendNotification: vi.fn(),
}))

import * as notif from "@tauri-apps/plugin-notification"

describe("useSystemNotify", () => {
  beforeEach(() => {
    vi.resetAllMocks()
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
})
