import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";

/**
 * 回归守卫：CSP 的 img-src 必须放行 connect-src 里声明的所有本地 sidecar 来源。
 *
 * 背景（v0.6.3 bug）：图文编辑器 / 挖掘评论用 `<img src="http://127.0.0.1:<port>/...">`
 * 展示 sidecar 提供的图片。connect-src 放行了 http://127.0.0.1:*（所以 axios 上传成功），
 * 但 img-src 漏了它 → WebView 的 CSP 把所有 <img> 本地图片加载拦掉，图片一律不显示
 * （表现为「能上传、缩略图/预览空白」）。这条测试钉死不变式：凡 connect-src 里的本地
 * sidecar 来源，img-src 必须也有。
 */
function parseCsp(csp: string): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const part of csp.split(";")) {
    const tokens = part.trim().split(/\s+/).filter(Boolean);
    if (!tokens.length) continue;
    const [name, ...sources] = tokens;
    map.set(name, sources);
  }
  return map;
}

// CI 跑 vitest 时 working-directory=frontend（见 .github/workflows/ci.yml），
// 故 cwd 相对路径可命中；为防从仓库根或别处运行，再向上找几层兜底。
function findTauriConf(): string {
  let dir = process.cwd();
  for (let i = 0; i < 5; i++) {
    for (const rel of ["src-tauri/tauri.conf.json", "frontend/src-tauri/tauri.conf.json"]) {
      const candidate = resolve(dir, rel);
      if (existsSync(candidate)) return candidate;
    }
    dir = dirname(dir);
  }
  throw new Error(`tauri.conf.json not found from cwd ${process.cwd()}`);
}

describe("tauri.conf.json CSP", () => {
  const conf = JSON.parse(readFileSync(findTauriConf(), "utf-8"));
  const csp: string = conf.app.security.csp;
  const directives = parseCsp(csp);

  it("img-src 放行 connect-src 里所有本地 sidecar 来源（防图片不显示回归）", () => {
    const connect = directives.get("connect-src") ?? [];
    const img = directives.get("img-src") ?? [];
    const sidecarOrigins = connect.filter((s) =>
      /^http:\/\/(127\.0\.0\.1|localhost):/.test(s),
    );
    // sanity：connect-src 确实声明了本地 sidecar 来源（否则本测试形同虚设）
    expect(sidecarOrigins.length).toBeGreaterThan(0);
    for (const origin of sidecarOrigins) {
      expect(img).toContain(origin);
    }
  });
});
