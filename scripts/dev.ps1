# 开发环境一键启动
# ================
# 流程：
#   1. 清理上次跑过的 sidecar / vite（按 .csm-dev/pids.json 里的 PID 杀）
#   2. 起 Python sidecar (csm_sidecar.main)，等它打印 handshake JSON
#   3. 把 {port, token} 写到 frontend/.env.local，让 vite 在 browser-dev
#      模式下知道怎么连 sidecar（VITE_SIDECAR_URL / VITE_SIDECAR_TOKEN）
#   4. 起 vite (npm run dev)
#   5. 落 PID 到 .csm-dev/pids.json，再次跑本脚本会先清这些
#
# 用法（在仓库根目录或脚本目录都行，PSScriptRoot 解析自身路径）：
#   .\scripts\dev.ps1                # 全开
#   .\scripts\dev.ps1 -Stop          # 仅清理上次的 sidecar + vite
#   .\scripts\dev.ps1 -SidecarOnly   # 只起 sidecar（前端用其他方式跑）
#   .\scripts\dev.ps1 -FrontendOnly  # 只起 vite，复用现有 .env.local
#                                     # （sidecar 已经在跑、token 没轮换才能用）
#
# 设计说明：
#   - sidecar 用 `python -u -m csm_sidecar.main` —— -u 关行缓冲，
#     第一行 handshake JSON 才会立刻可见；不然 stdout 默认是块缓冲，
#     脚本会卡在等 handshake 直到超时。
#   - vite 通过 npm.cmd 启动，子进程是 node。Stop 用 taskkill /T /F 拉
#     整个树，因为 Stop-Process 不杀子进程，npm.cmd 死了 node 还活着。
#   - .env.local 是 vite 启动时读的环境变量；vite 进程跑起来之后改它
#     不会热更（必须重启 vite）。所以脚本顺序是 sidecar → 写 env →
#     起 vite。
#   - 不在前台 tail 日志：起完就返回 prompt，让用户继续操作。日志路径
#     在 .csm-dev/ 下，需要时 `Get-Content -Tail 20 -Wait` 自己看。

[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$SidecarOnly,
    [switch]$FrontendOnly,
    [int]$HandshakeTimeoutSec = 15,
    [int]$ViteTimeoutSec = 30
)

$ErrorActionPreference = "Stop"

# ─── 仓库根目录解析 ────────────────────────────────────────────────
# 脚本必然在 <repo>/scripts/ 下，所以 root = 脚本目录的父目录。
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$RepoRoot/sidecar/csm_sidecar")) {
    throw "Repo root not found at $RepoRoot (no sidecar/csm_sidecar/)"
}

$FrontendDir = Join-Path $RepoRoot "frontend"
$EnvLocal    = Join-Path $FrontendDir ".env.local"
$StateDir    = Join-Path $RepoRoot ".csm-dev"
$PidsFile    = Join-Path $StateDir "pids.json"
$SidecarLog  = Join-Path $StateDir "sidecar.log"
$SidecarErr  = Join-Path $StateDir "sidecar.err.log"
$ViteLog     = Join-Path $StateDir "vite.log"
$ViteErr     = Join-Path $StateDir "vite.err.log"

$null = New-Item -ItemType Directory -Force -Path $StateDir

# ─── 输出小工具 ────────────────────────────────────────────────────
function Write-Step($t) { Write-Host "`n>> $t" -ForegroundColor Cyan }
function Write-Ok($t)   { Write-Host "   OK $t" -ForegroundColor Green }
function Write-Warn2($t){ Write-Host "   !! $t" -ForegroundColor Yellow }
function Write-Err2($t) { Write-Host "   ER $t" -ForegroundColor Red }

# ─── 进程管理 ──────────────────────────────────────────────────────
# taskkill /T /F = 杀整个进程树（含子进程）。npm.cmd 起 vite 后子进程
# 是 node.exe，单杀父 cmd 会留下孤儿 node 一直占着 5173。
function Stop-Tree($label, $procPid) {
    if (-not $procPid) { return }
    if (-not (Get-Process -Id $procPid -ErrorAction SilentlyContinue)) {
        Write-Ok "$label not running (PID $procPid stale)"
        return
    }
    $null = & taskkill.exe /T /F /PID $procPid 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "stopped $label (PID $procPid + children)"
    } else {
        Write-Warn2 "taskkill returned $LASTEXITCODE for $label (PID $procPid)"
    }
}

function Stop-Existing {
    if (-not (Test-Path $PidsFile)) {
        Write-Ok "no previous dev state"
        return
    }
    try {
        $state = Get-Content $PidsFile -Raw -Encoding utf8 | ConvertFrom-Json
    } catch {
        Write-Warn2 "pids.json unreadable, skipping cleanup"
        return
    }
    Stop-Tree "sidecar" $state.sidecar
    Stop-Tree "vite"    $state.vite
    Remove-Item $PidsFile -ErrorAction SilentlyContinue
}

# ─── Sidecar 启动 ──────────────────────────────────────────────────
function Start-Sidecar {
    Write-Step "Starting Python sidecar"
    if (Test-Path $SidecarLog) { Remove-Item $SidecarLog -Force }
    if (Test-Path $SidecarErr) { Remove-Item $SidecarErr -Force }

    # ⚠ 关闭 parent watchdog —— 默认行为是 sidecar 检测父进程消失就自杀
    # （Tauri 模式下父进程是 csm-tauri.exe，关闭窗口时连带退出 sidecar）。
    # 但 dev 脚本里"父进程"是 PowerShell shell，脚本一返回 shell 也散，
    # 30s 内 sidecar 就会自杀。本脚本主动管理 PID（脚本 -Stop 时杀），
    # 所以禁用监护让 sidecar 独立活到 -Stop。
    # Start-Process 在 PS 5.1 没有 -Environment 参数，临时改父 shell 的
    # $env，子进程继承；调完恢复。
    $prevWatchdog = $env:CSM_SIDECAR_PARENT_WATCHDOG
    $env:CSM_SIDECAR_PARENT_WATCHDOG = "0"
    try {
        # python -u 关 stdout 缓冲，第一行 handshake JSON 才能即时拿到。
        $proc = Start-Process -FilePath "python" `
            -ArgumentList @("-u", "-m", "csm_sidecar.main") `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $SidecarLog `
            -RedirectStandardError $SidecarErr `
            -PassThru `
            -WindowStyle Hidden
    } finally {
        if ($null -eq $prevWatchdog) {
            Remove-Item Env:CSM_SIDECAR_PARENT_WATCHDOG -ErrorAction SilentlyContinue
        } else {
            $env:CSM_SIDECAR_PARENT_WATCHDOG = $prevWatchdog
        }
    }

    # 轮询日志直到看到 handshake JSON 行：{"port": ..., "token": "..."}。
    # 前几行是 INFO 日志，不要被它们干扰。
    $deadline = (Get-Date).AddSeconds($HandshakeTimeoutSec)
    $handshake = $null
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $SidecarLog) {
            $lines = Get-Content $SidecarLog -ErrorAction SilentlyContinue
            foreach ($line in $lines) {
                if ($line -match '^\s*\{.*"port".*"token".*\}\s*$') {
                    try { $handshake = $line | ConvertFrom-Json } catch { }
                    if ($handshake) { break }
                }
            }
            if ($handshake) { break }
        }
        if ($proc.HasExited) {
            $err = if (Test-Path $SidecarErr) { Get-Content $SidecarErr -Raw } else { "" }
            $out = if (Test-Path $SidecarLog) { Get-Content $SidecarLog -Raw } else { "" }
            throw "sidecar exited (code $($proc.ExitCode))`nSTDERR:`n$err`nSTDOUT:`n$out"
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $handshake) {
        Stop-Tree "sidecar (timeout)" $proc.Id
        throw "sidecar didn't print handshake within $HandshakeTimeoutSec s — see $SidecarLog"
    }
    Write-Ok "sidecar on port $($handshake.port) (PID $($proc.Id))"
    return @{ Process = $proc; Port = $handshake.port; Token = $handshake.token }
}

# ─── 写 .env.local ─────────────────────────────────────────────────
function Write-EnvLocal($port, $token) {
    Write-Step "Writing $EnvLocal"
    # 不用 Set-Content -Encoding utf8 —— 5.1 会带 BOM。dotenv 一般容忍，
    # 但显式写 UTF-8 不加 BOM 最稳。
    $content = @"
# Auto-generated by scripts/dev.ps1 — regenerated on every run.
# Tauri shell 模式下这两个变量是被忽略的（Tauri 自己注入 handshake）。
VITE_SIDECAR_URL=http://127.0.0.1:$port
VITE_SIDECAR_TOKEN=$token
"@
    [System.IO.File]::WriteAllText($EnvLocal, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Ok ".env.local written (port=$port)"
}

# ─── Vite 启动 ─────────────────────────────────────────────────────
function Start-Vite {
    Write-Step "Starting Vite dev server"
    if (Test-Path $ViteLog) { Remove-Item $ViteLog -Force }
    if (Test-Path $ViteErr) { Remove-Item $ViteErr -Force }

    # npm.cmd 是 Windows 上 npm 的可执行包装；直接调 "npm" 在某些环境
    # 下会走 PowerShell 函数而不是真正的 cmd 包装。
    $proc = Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $FrontendDir `
        -RedirectStandardOutput $ViteLog `
        -RedirectStandardError $ViteErr `
        -PassThru `
        -WindowStyle Hidden

    # 等 "Local:" 字样出现 = vite 报告自己 ready。也容忍 stderr/stdout 混
    # 写的情况：两边都看。
    $deadline = (Get-Date).AddSeconds($ViteTimeoutSec)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        $combined = ""
        if (Test-Path $ViteLog) { $combined += (Get-Content $ViteLog -Raw -ErrorAction SilentlyContinue) }
        if (Test-Path $ViteErr) { $combined += (Get-Content $ViteErr -Raw -ErrorAction SilentlyContinue) }
        # vite 5 用 ANSI 颜色码包装输出，"VITE v5.x ready in NNN ms" 一行
        # 实际是 "\e[32m\e[1mVITE\e[22m v5.4.21\e[39m \e[2mready in \e[0m\e[1m379\e[22m..."
        # 在 "ready in" 和数字之间塞了 ANSI 序列，\s+\d+ 不匹配。直接匹
        # 配 "ready in" 字面就够 —— 出现这字符串=vite 已就绪。
        if ($combined -match "ready in") {
            $ready = $true
            break
        }
        if ($proc.HasExited) {
            $err = if (Test-Path $ViteErr) { Get-Content $ViteErr -Raw } else { "" }
            throw "vite exited (code $($proc.ExitCode))`nSTDERR:`n$err"
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) {
        Write-Warn2 "vite didn't report ready within $ViteTimeoutSec s — check $ViteLog"
    } else {
        Write-Ok "vite ready (PID $($proc.Id))"
    }
    return $proc
}

# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

if ($Stop) {
    Write-Step "Stopping dev processes"
    Stop-Existing
    Write-Host ""
    exit 0
}

# 先清一遍，避免端口被上次的进程占着 / 出现幽灵 sidecar
Write-Step "Cleaning previous dev state (if any)"
Stop-Existing

# Sidecar
$sidecarPid = $null
$sidecarPort = $null
if (-not $FrontendOnly) {
    $sc = Start-Sidecar
    Write-EnvLocal $sc.Port $sc.Token
    $sidecarPid = $sc.Process.Id
    $sidecarPort = $sc.Port
} else {
    Write-Warn2 "skipping sidecar (FrontendOnly) — assuming .env.local already valid"
    if (-not (Test-Path $EnvLocal)) {
        throw "FrontendOnly but $EnvLocal doesn't exist — run without -FrontendOnly first"
    }
}

# Vite
$vitePid = $null
if (-not $SidecarOnly) {
    $vp = Start-Vite
    $vitePid = $vp.Id
}

# 落 PID 给下次 -Stop 用
$state = [PSCustomObject]@{
    sidecar = $sidecarPid
    vite    = $vitePid
    port    = $sidecarPort
    started = (Get-Date).ToString("o")
}
$state | ConvertTo-Json | Set-Content -Path $PidsFile -Encoding utf8

# ─── 收尾输出 ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "==================== DEV ENV READY ====================" -ForegroundColor Green
if ($sidecarPid) {
    Write-Host ("  Sidecar  PID {0,-6}  port {1,-5}  log: {2}" -f $sidecarPid, $sidecarPort, $SidecarLog)
}
if ($vitePid)    {
    Write-Host ("  Vite     PID {0,-6}  http://localhost:5173    log: {1}" -f $vitePid, $ViteLog)
}
Write-Host ""
Write-Host "  Tail sidecar : Get-Content $SidecarLog -Tail 20 -Wait" -ForegroundColor DarkGray
Write-Host "  Tail vite    : Get-Content $ViteLog -Tail 20 -Wait" -ForegroundColor DarkGray
Write-Host "  Stop all     : .\scripts\dev.ps1 -Stop"               -ForegroundColor DarkGray
Write-Host "=======================================================" -ForegroundColor Green
