# 应用热更新（GitHub Releases + 独立 updater.exe）

**Date:** 2026-05-07
**Status:** Approved, awaiting implementation plan

## 背景与动机

CSM 当前发版方式：本地 PyInstaller 打包 → zip → 微信/飞书发给同事。这导致：

1. 每次手工打包，发版几十分钟
2. 版本号靠人脑维护，容易和发出去的包错位
3. 同事用旧版报 bug 时，作者要先确认对方是哪个版本
4. 无标准变更日志，发版后用户不知道改了啥

希望：

- **自动化构建**：推 git tag 自动 PyInstaller 出包
- **集中分发**：所有版本归档到 GitHub Releases
- **应用内升级**：用户启动时静默检查 + 设置页"检查更新"按钮，一键下载 + 自动替换
- **变更日志**：单一来源（CHANGELOG.md）→ 自动同步到 GitHub Release 页 + 客户端升级对话框

## 范围

| 项 | 在范围内 |
|---|---|
| GitHub Actions 自动构建（push tag 触发）| ✅ |
| GitHub 私有 repo Releases 作为分发渠道 | ✅ |
| CSM 内嵌 updater 客户端（检查 + 下载）| ✅ |
| 独立 updater.exe（执行替换 + 启动）| ✅ |
| Windows 文件锁问题处理 | ✅ |
| 失败回滚 | ✅ |
| 全量包分发（每次完整 zip）| ✅ |
| 增量差分包 | ❌（10 人体量不值得） |
| 多渠道分发（自有 CDN / 对象存储）| ❌ |
| 代码签名证书 | ❌ |
| 自动后台静默升级（不询问）| ❌ |

## 用户场景与团队规模

- **10 个用户**，公司内部使用
- **闭源**，私有 GitHub repo
- 用户一般在主分支跟最新版本，**强制更新极少使用**
- 网络环境：能访问 GitHub（必要时通过公司代理）

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│  开发侧                                                          │
│  ┌──────────┐   git tag v0.2.0 + push   ┌──────────────────────┐│
│  │ 本地仓库 │ ───────────────────────────▶│ GitHub Actions       ││
│  └──────────┘                            │ - 校验 tag==_version ││
│                                          │ - 构建 CSM.exe       ││
│                                          │ - 构建 updater.exe   ││
│                                          │ - 打 CSM-v0.2.0.zip  ││
│                                          │ - 算 SHA256          ││
│                                          │ - 抽 CHANGELOG 段落  ││
│                                          │ - 创建 Release       ││
│                                          │ - 上传 zip + manifest││
│                                          └────────┬─────────────┘│
└───────────────────────────────────────────────────│──────────────┘
                                                    │
                              GitHub Releases (私有)
                                                    │
┌───────────────────────────────────────────────────│──────────────┐
│  用户侧                                            ▼             │
│  ┌──────────────────────┐                                        │
│  │ CSM.exe              │ 启动 / 设置页 [检查更新]                │
│  │  csm_core/           │                                        │
│  │   updater_client/    │ ──── GET /releases/latest ──────────▶  │
│  │   - checker.py       │      Header: Authorization: Bearer PAT │
│  │   - downloader.py    │                                        │
│  │   - github_client.py │ ◀── manifest.json + zip URL ─────────  │
│  └──────────┬───────────┘                                        │
│             │ 用户点 [立即升级]                                    │
│             │ 下载到 %TEMP%\csm_update\CSM-v0.2.0.zip             │
│             │ SHA256 校验通过                                      │
│             │ spawn updater.exe + sys.exit(0)                     │
│             ▼                                                      │
│  ┌──────────────────┐                                             │
│  │ updater.exe       │ 等待主进程 PID 退出（≤ 10s）               │
│  │ (~30MB onefile)  │ 备份 install_dir → install_dir.bak          │
│  │                   │ 解压 zip 到 install_dir.new                 │
│  │                   │ 移动 .new → install_dir                     │
│  │                   │ 启动 install_dir\CSM.exe                    │
│  │                   │ 失败 → 回滚 .bak → 启动旧版 + 写错误日志    │
│  └──────────────────┘                                             │
└──────────────────────────────────────────────────────────────────┘
```

## 文件清单

```
新增：
  .github/workflows/release.yml         # tag 触发的 CI
  CHANGELOG.md                          # Keep a Changelog 格式
  scripts/release.py                    # 一键发版脚本
  scripts/release_check.py              # CI 中校验 tag == _version
  scripts/extract_changelog.py          # 从 CHANGELOG.md 抽取版本段落

  csm_gui/_version.py                   # __version__ = "0.1.0"

  csm_core/updater_client/
  ├── __init__.py
  ├── manifest.py                       # GitHub release JSON 解析
  ├── checker.py                        # check_for_update() → UpdateInfo
  ├── downloader.py                     # 流式下载 + SHA256 + 进度
  ├── github_client.py                  # GitHub API + PAT 鉴权
  └── _token.py                         # CI 注入的 PAT（gitignore）

  csm_gui/widgets/
  ├── update_dialog.py                  # 升级提示对话框（含 changelog）
  └── update_progress_dialog.py         # 下载进度

  updater/                              # 独立 updater 工程
  ├── main.py
  ├── updater.spec                      # PyInstaller onefile spec
  └── README.md

修改：
  csm_gui/main_window.py                # 启动时异步检查更新
  csm_gui/pages/settings_page.py        # 加 "关于" 区块 + 检查更新按钮
  CSM.spec                              # 把 _version 写入 build 元数据
  pyproject.toml                        # version 改 dynamic（读 _version.py）
  .gitignore                            # 加 csm_core/updater_client/_token.py
```

## 版本号单一来源规则

`csm_gui/_version.py` 是**唯一**版本号源：

```python
# csm_gui/_version.py
__version__ = "0.1.0"
```

`pyproject.toml` 通过动态读取：

```toml
[project]
dynamic = ["version"]

[tool.setuptools.dynamic]
version = { attr = "csm_gui._version.__version__" }
```

CI 在 tag push 时跑 `scripts/release_check.py`：

```python
# 校验 tag (v0.2.0) 去掉 v 前缀后等于 __version__
# 不一致直接 fail，强制开发者一致
```

这从根上**消除"版本对不齐"**问题。

## CHANGELOG.md 格式（Keep a Changelog）

```markdown
# 变更日志

## [Unreleased]

### Added
- (开发中的新功能)

## [0.2.0] - 2026-05-07

### Added
- 系统托盘后台运行
- 创作区右侧内容查重面板

### Changed
- 设置页布局调整

### Fixed
- 修复批量导出进度条偶发卡死

## [0.1.0] - 2026-04-15

### Added
- 项目初版
```

子标题固定六类：`Added` / `Changed` / `Fixed` / `Removed` / `Deprecated` / `Security`。

`scripts/extract_changelog.py` 在 CI 中抽取 `[0.2.0]` 段落作为 GitHub Release body，CSM 客户端通过 GitHub API 拉到这段 markdown 渲染给用户。

## 发版工作流（开发者侧）

### 日常开发

```bash
git add .
git commit -m "feat: 加托盘菜单"
# 顺手编辑 CHANGELOG.md 的 [Unreleased] 段写一行
git push origin main
```

### 一键发版

```bash
python scripts/release.py 0.2.0
```

脚本步骤：

1. 校验 git working tree 干净，否则拒绝
2. 校验当前在 `main` 分支
3. 校验 0.2.0 是合法 semver 且大于当前 `__version__`
4. 写入 `csm_gui/_version.py`
5. 改 CHANGELOG.md：`[Unreleased]` → `[0.2.0] - 今天日期` + 新开空 `[Unreleased]` 段
6. `git add` + `git commit -m "release: v0.2.0"` + `git tag v0.2.0` + `git push origin main --tags`
7. 浏览器打开 GitHub Actions 页查看 CI 进度

之后 CI 接管，5–10 分钟出 Release，10 个用户启动 CSM 即收到升级提示。

## CI 流程（GitHub Actions）

```yaml
# .github/workflows/release.yml （示意）
name: Release
on:
  push:
    tags: ['v*.*.*']

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: 校验 tag 与 _version 一致
        run: python scripts/release_check.py "${{ github.ref_name }}"
      
      - name: 安装依赖
        run: |
          pip install -e .[gui]
          pip install pyinstaller
      
      - name: 注入 PAT 到 _token.py
        run: |
          echo "TOKEN = '${{ secrets.CSM_RELEASE_PAT }}'" > csm_core/updater_client/_token.py
      
      - name: 构建主程序
        run: pyinstaller CSM.spec
      
      - name: 构建 updater
        run: pyinstaller updater/updater.spec
      
      - name: 打包 zip
        run: |
          Compress-Archive -Path dist/CSM -DestinationPath CSM-${{ github.ref_name }}.zip
      
      - name: 算 SHA256 + 生成 manifest.json
        run: python scripts/build_manifest.py "${{ github.ref_name }}"
      
      - name: 抽取 CHANGELOG
        id: changelog
        run: python scripts/extract_changelog.py "${{ github.ref_name }}"
      
      - name: 创建 Release
        uses: softprops/action-gh-release@v2
        with:
          body: ${{ steps.changelog.outputs.body }}
          files: |
            CSM-${{ github.ref_name }}.zip
            dist/updater.exe
            manifest.json
```

`manifest.json` 结构：

```json
{
  "version": "0.2.0",
  "released_at": "2026-05-07T08:00:00Z",
  "asset_url": "https://github.com/.../CSM-v0.2.0.zip",
  "asset_size": 243814092,
  "sha256": "abc123...",
  "min_compatible_version": "0.1.0"
}
```

## 客户端 update_client 数据流

### 启动时静默检查

```python
# main_window.py
def __init__(self, ...):
    ...
    QTimer.singleShot(2000, self._check_for_update_silent)  # 启动后 2s 异步

def _check_for_update_silent(self) -> None:
    worker = UpdateCheckWorker()
    worker.finished.connect(self._on_update_check_done)
    worker.start()

def _on_update_check_done(self, info: UpdateInfo | None) -> None:
    if info is None or not info.has_update:
        return
    # 主页右上角小红点 + 托盘 tooltip 加更新提示
    self.home.set_update_badge(info.version)
    self.tray_manager.set_update_available(info.version)
```

网络失败、超时（5s）、限流均**静默忽略**，不弹窗不阻塞启动。

### 用户主动检查

设置页"关于"区块：

```
[关于 CSM]
  当前版本：v0.1.0
  发布日期：2026-04-15
  
  [检查更新]   最后检查：2026-05-07 14:23
```

点击 [检查更新]：
- 已是最新 → InfoBar.success "已是最新版本 v0.1.0"
- 有新版 → 弹 UpdateDialog（同上）
- 失败 → InfoBar.error "检查更新失败：<原因>"

### UpdateDialog（升级提示）

```
┌── 发现新版本 ────────────────────────────────┐
│                                              │
│  当前版本：v0.1.0                             │
│  最新版本：v0.2.0  (2026-05-07)               │
│                                              │
│  ─ 变更日志 ─                                │
│  ### Added                                   │
│  - 系统托盘后台运行                           │
│  - 创作区右侧内容查重面板                      │
│                                              │
│  ### Fixed                                   │
│  - 修复批量导出进度条偶发卡死                  │
│                                              │
│                                              │
│           [稍后再说]      [立即升级]          │
└──────────────────────────────────────────────┘
```

点击 [立即升级]：
- 弹 UpdateProgressDialog（进度条 + 速度 + 取消按钮）
- 流式下载到 `%TEMP%\csm_update\CSM-v0.2.0.zip`
- SHA256 校验
- 校验通过 → spawn `updater.exe` + 主程序 `sys.exit(0)`

## updater.exe 流程

启动参数：`updater.exe --pid <main_pid> --zip <temp_zip> --target <install_dir>`

```python
# updater/main.py 伪码
def main():
    args = parse_args()
    
    # 1. 等主进程退出
    wait_for_pid_exit(args.pid, timeout=10)
    
    # 2. 备份当前安装
    target = Path(args.target)
    backup = target.parent / f"{target.name}.bak"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(target, backup)
    
    try:
        # 3. 解压新版本到临时目录
        new_dir = target.parent / f"{target.name}.new"
        if new_dir.exists():
            shutil.rmtree(new_dir)
        with zipfile.ZipFile(args.zip) as zf:
            zf.extractall(new_dir.parent)
        
        # 4. 替换
        shutil.rmtree(target)
        shutil.move(new_dir, target)
        
        # 5. 启动新版主程序
        subprocess.Popen([target / "CSM.exe"], cwd=target)
        
        # 6. 清理（保留 .bak 一次启动周期再删）
        os.unlink(args.zip)
        
    except Exception as e:
        # 失败回滚
        if target.exists():
            shutil.rmtree(target)
        shutil.move(backup, target)
        write_error_log(e)
        subprocess.Popen([target / "CSM.exe"], cwd=target)
        sys.exit(1)
```

`updater.exe` 用 PyInstaller `--onefile` 模式打包，约 30 MB（独立 Python runtime 但只 import stdlib）。

## Token 管理

- 创建 GitHub Fine-grained PAT，权限：
  - 仓库：仅 CSM 私有 repo
  - 权限：Contents: Read（足够读 release + asset）
- Token 存放：
  - **CI 侧**：GitHub Secrets `CSM_RELEASE_PAT`
  - **客户端侧**：CI 构建时注入到 `csm_core/updater_client/_token.py`（gitignore，不进 git 历史）
- 轮换策略：
  - 6 个月手动轮换一次（CI 中可加到期提醒）
  - 轮换时所有用户客户端必须升级（旧 token 失效后无法检查更新，但**不阻塞使用 CSM**）
- 风险控制：
  - 10 人内部团队，token 即使泄露后果有限（最多别人能看到代码，但同事本就有访问权）
  - 团队规模 > 100 时迁移到 GitHub OAuth Device Flow（用户首启自助授权）

## 错误处理

| 场景 | 行为 |
|---|---|
| 启动检查无网络 | 静默忽略，下次启动再查 |
| GitHub API 超时 / 503 | 静默忽略 |
| GitHub API 403（限流 / token 失效）| 启动检查静默；手动检查时提示用户"鉴权失败，联系作者" |
| manifest.json 解析失败 | 同上，记日志 |
| 下载中断 | 支持 HTTP Range 断点续传，3 次失败后报错"下载失败，请重试" |
| SHA256 校验失败 | 删除 zip + 提示"下载文件损坏，请重试" |
| %TEMP% 写入失败（磁盘满）| 提示"临时目录写入失败，清理磁盘后重试" |
| updater.exe 启动失败 | 主程序未退出，提示"升级器启动失败，请手动重新打开 CSM" |
| updater 替换中文件被占用（杀软扫描）| 重试 3 次（每次 1s），仍失败回滚 .bak |
| updater 启动新主程序失败 | 写 `<config_dir>/update_error.log`，回退到 .bak |
| 用户在创作中收到提示 | 默认按钮永远是 [稍后再说]，永不自动升级 |
| 强制更新（manifest.min_compatible_version > 当前）| 进入主程序前阻塞，仅显示升级对话框，[稍后再说] 按钮置灰 |

## 回滚策略

- updater 在替换前**始终**备份当前安装到 `<install_dir>.bak`
- 替换失败 → 删除 `<install_dir>` → 把 `.bak` 改名回去 → 启动旧版
- 替换成功后保留 `.bak` 直到下一次启动 CSM 主程序成功验证版本（即新版能正常起来）
- 用户也可手动从 `<install_dir>.bak` 恢复（README 写明）

## 测试策略

### CI 单测

- `manifest.py`：构造合法/非法 GitHub release JSON 解析；缺字段处理
- `checker.py`：mock requests，验证版本比较 / 超时 / 限流处理
- `downloader.py`：mock 流式下载，SHA256 失败时清理临时文件；中断 3 次后报错
- `github_client.py`：mock API；不同 HTTP 状态码处理

### 集成测试（手动 + CI 可部分覆盖）

- 本地起 mock GitHub server，跑完整链路 check → download → updater
- 模拟 updater 替换失败（mock `shutil.move` 抛异常），验证 .bak 回滚
- 用 fixture 跑 `release.py` 脚本，验证 _version + CHANGELOG 改动正确

### 自检（CI 内置）

- `release_check.py` 在 PR 阶段就校验版本号语义合法（semver）
- 把 manifest 校验也写成 CI 任务，确保上传前 SHA256 与 zip 一致

### 手动验证清单

- 推 v0.0.1-test 测试 tag → CI 应失败（version 不在 _version.py 里）→ 验证校验生效
- 推 v0.1.1 → CI 通过 → 客户端 v0.1.0 启动应收到提示
- 点击立即升级 → 完整跑通 → 验证 .bak 创建 + 删除时机
- 杀掉 updater.exe 进程模拟失败 → 重启 CSM 应是旧版（自动回滚）

## Out of Scope

- 增量差分包（10 人不值得做）
- 自动后台静默升级（必须显式确认）
- 多渠道分发（如未来加企微、官网下载，再立项）
- 强制更新的 UI 美化（先做能用的）
- 代码签名证书（未来增强，¥1000+/年成本）
- 灰度发布 / A/B 升级
- 多语言版本支持
- macOS / Linux 自动更新（CSM 仅 Win 分发）

## 实施顺序建议

1. `csm_gui/_version.py` + `pyproject.toml` 改 dynamic version
2. `CHANGELOG.md` 初始化（包含 [0.1.0] 当前版本）
3. `scripts/release.py` + `scripts/release_check.py` + `scripts/extract_changelog.py`
4. 本地手动跑一次 release.py 验证脚本（dry-run 模式 + 真实 push）
5. `.github/workflows/release.yml` + 推 v0.1.1-test 验证 CI
6. `csm_core/updater_client/` 客户端模块 + 单测
7. `update_dialog.py` + `update_progress_dialog.py`
8. 设置页"关于"区块 + 检查更新按钮
9. MainWindow 启动检查 + 集成
10. `updater/` 独立工程 + spec
11. PyInstaller 冒烟（重点：updater.exe 能独立运行 + token 注入）
12. 完整 e2e 验证：v0.1.0 装机后推 v0.1.1 验证用户能升级成功

## 附录：发版 SOP（开发者备查）

> 这一节将作为 README.md 或 docs/RELEASING.md 的一部分发布给团队成员（如果有协作）。

**首次准备**（一次性）：

1. 创建 GitHub Fine-grained PAT，权限 `Contents: Read`，仅 CSM repo
2. 在仓库 Settings → Secrets 加 `CSM_RELEASE_PAT`
3. 确保 main 分支有 .github/workflows/release.yml

**每次发版**（< 1 分钟）：

1. 编辑 CHANGELOG.md 的 `[Unreleased]` 段，写本次改动（按 Added/Changed/Fixed 分组）
2. 跑 `python scripts/release.py X.Y.Z`
3. 浏览器跟踪 GitHub Actions，5–10 分钟后 Release 自动创建
4. 通知团队（飞书/微信群发"v0.2.0 已发布"）→ 同事下次启动 CSM 自动收到提示

**发版后立即检查**：

- GitHub Release 页面是否包含 zip + updater.exe + manifest.json
- changelog 是否正确显示
- 自己用 v0.1.0 旧版启动一次，看升级提示是否出现
