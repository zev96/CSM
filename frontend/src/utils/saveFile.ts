/**
 * 共享下载工具 —— 把一个带 token 的 sidecar URL 下载成文件。
 * Tauri 环境走原生「另存为」对话框；浏览器 dev 回退 <a download>。
 */
export async function saveUrlToFile(
  url: string,
  defaultName: string,
  filter?: { name: string; extensions: string[] },
): Promise<void> {
  const isTauri =
    typeof window !== "undefined" &&
    // @ts-expect-error — ambient Tauri global
    Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);

  if (!isTauri) {
    // 浏览器 dev 模式 fallback —— 走 <a download> 路径
    const a = document.createElement("a");
    a.href = url;
    a.download = defaultName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return;
  }

  const { save } = await import("@tauri-apps/plugin-dialog");
  const path = await save({
    defaultPath: defaultName,
    filters: filter ? [filter] : undefined,
  });
  if (!path) return; // 用户取消

  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const bytes = new Uint8Array(await resp.arrayBuffer());
  const { writeFile } = await import("@tauri-apps/plugin-fs");
  await writeFile(path, bytes);
}
