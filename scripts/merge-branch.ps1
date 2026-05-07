# 分支合并到 master 一键脚本
# ============================
# 用法：在分支 worktree 里跑（D:\CSM\.claude\worktrees\<分支名>）
#   .\scripts\merge-branch.ps1                   # 交互式
#   .\scripts\merge-branch.ps1 -Message "feat: xxx"  # 直接传提交信息
#   .\scripts\merge-branch.ps1 -KeepBranch       # 合并后保留分支（默认删除）
#
# 流程：
#   1. 校验当前在分支 worktree（不能是 master）
#   2. 有未提交改动 → 提交（提示输入 message 或用 -Message 参数）
#   3. 切到主工作区 D:\CSM
#   4. 主工作区有杂改动 → 自动 stash（可在脚本结束时 pop 或留着）
#   5. fast-forward 合并分支
#   6. 删除分支 worktree + 分支引用（除非 -KeepBranch）

[CmdletBinding()]
param(
    [string]$Message = "",
    [switch]$KeepBranch,
    [string]$MasterPath = "D:\CSM"
)

$ErrorActionPreference = "Stop"

function Write-Step($text) {
    Write-Host "`n>> $text" -ForegroundColor Cyan
}

function Write-Ok($text) {
    Write-Host "   OK $text" -ForegroundColor Green
}

function Write-Warn($text) {
    Write-Host "   !  $text" -ForegroundColor Yellow
}

function Fail($text) {
    Write-Host "`nERROR: $text" -ForegroundColor Red
    exit 1
}

# ── 1. 校验位置 ─────────────────────────────────────────────────────────
Write-Step "校验当前位置"
$branch = (git branch --show-current).Trim()
if (-not $branch) { Fail "当前不在任何 git 分支里" }
if ($branch -eq "master") { Fail "当前已在 master，请在分支 worktree 里运行" }
$worktreePath = (git rev-parse --show-toplevel).Trim()
Write-Ok "分支 = $branch"
Write-Ok "worktree = $worktreePath"

# ── 2. 提交未保存改动 ──────────────────────────────────────────────────
Write-Step "检查分支是否有未提交改动"
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "   有未提交改动："
    git status --short | ForEach-Object { Write-Host "     $_" }
    if (-not $Message) {
        $Message = Read-Host "`n   请输入提交信息 (commit message)"
        if (-not $Message) { Fail "提交信息不能为空" }
    }
    git add -A
    if ($LASTEXITCODE -ne 0) { Fail "git add 失败" }
    $body = @"
$Message

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
"@
    git commit -m $body
    if ($LASTEXITCODE -ne 0) { Fail "git commit 失败" }
    Write-Ok "已提交"
} else {
    Write-Ok "工作区干净，无需提交"
}

# 校验分支真的领先 master
$ahead = (git log "master..HEAD" --oneline | Measure-Object).Count
if ($ahead -eq 0) {
    Fail "分支没有领先 master 的提交，无需合并"
}
Write-Ok "分支领先 master $ahead 个 commit"

# ── 3. 切到主工作区 ────────────────────────────────────────────────────
Write-Step "切换到主工作区 $MasterPath"
if (-not (Test-Path $MasterPath)) { Fail "主工作区不存在: $MasterPath" }
Push-Location $MasterPath

try {
    # ── 4. stash 杂改动 ────────────────────────────────────────────────
    Write-Step "检查主工作区是否干净"
    $masterDirty = git status --porcelain
    $stashed = $false
    if ($masterDirty) {
        Write-Warn "主工作区有未提交改动，自动 stash"
        $stashName = "auto-stash before merging $branch"
        git stash push -u -m $stashName | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "stash 失败" }
        $stashed = $true
        Write-Ok "已 stash: $stashName"
    } else {
        Write-Ok "主工作区干净"
    }

    # ── 5. fast-forward 合并 ───────────────────────────────────────────
    Write-Step "Fast-forward 合并 $branch"
    git merge --ff-only $branch
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "ff-only 失败，可能 master 有新提交。要尝试普通 merge 吗？"
        $yn = Read-Host "   产生 merge commit (y/N)"
        if ($yn -eq "y") {
            git merge $branch
            if ($LASTEXITCODE -ne 0) { Fail "合并冲突，请手动解决后再运行 git commit" }
        } else {
            Fail "已取消合并"
        }
    }
    Write-Ok "合并完成"

    # ── 6. 清理分支 worktree + 引用 ────────────────────────────────────
    if (-not $KeepBranch) {
        Write-Step "清理 worktree + 分支引用"
        git worktree remove $worktreePath --force
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "已删除 worktree: $worktreePath"
        } else {
            Write-Warn "worktree 删除失败（可能正被占用），稍后手动: git worktree remove $worktreePath"
        }
        git branch -d $branch
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "已删除分支引用: $branch"
        } else {
            Write-Warn "分支引用删除失败，稍后手动: git branch -d $branch"
        }
    } else {
        Write-Ok "-KeepBranch 已设置，分支保留"
    }

    # ── 提示 stash 状态 ────────────────────────────────────────────────
    if ($stashed) {
        Write-Host ""
        Write-Warn "之前 stash 的改动还在 stash 列表里，自己决定要不要恢复："
        Write-Host "     git stash list                     # 查看"
        Write-Host "     git stash show -p stash@{0}        # 看差异"
        Write-Host "     git stash pop                      # 恢复"
        Write-Host "     git stash drop stash@{0}           # 丢弃"
    }

    Write-Host "`n=== 合并完成 ===" -ForegroundColor Green
    Write-Host "现在可以直接在 $MasterPath 运行 main.py" -ForegroundColor Green
} finally {
    Pop-Location
}
