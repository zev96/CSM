//! 应用热更新 —— 启动 updater.exe + 退出主进程
//!
//! Flow（跟 updater/main.py 配套）：
//!   1. 前端 `await ctrl.final === "restart"` 后 invoke('install_and_restart')
//!   2. 解析 install_dir（current_exe 的父目录）+ updater.exe 路径
//!      （release：从 resource_dir 拿；dev：跳出 dev 占位错误，让前端 toast）
//!   3. spawn updater.exe，传 --pid <self> --zip <zip_path> --target <install_dir>
//!      Windows 用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP，避免子进程跟着主进程一起死
//!   4. 调 app.exit(0)，让主进程退出；updater 等 pid 没了之后接管文件替换
//!
//! Dev 模式约束：updater.exe 不在 resource_dir 里（PyInstaller onefile 产物需要走 release 打包流程
//! 才会出现在 resources/）。dev 调用会返回错误字符串 "updater_not_found: ..."，
//! 前端识别后给友好提示，不让 dev 流程被异常卡死。
use std::path::{Path, PathBuf};
use std::process::Command;

use tauri::{AppHandle, Manager};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const DETACHED_PROCESS: u32 = 0x0000_0008;
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

/// 查找 updater.exe。
///
/// Tauri 2 + NSIS 实际布局（v0.4.1 release CI 实测）：
///   <install>/csm-tauri.exe
///   <install>/csm-sidecar.exe
///   <install>/binaries/updater.exe   ← resources 配置成 "binaries/updater.exe"
///                                       Tauri 保留相对路径
///
/// 所以**优先**找 `<install>/binaries/updater.exe`；如果找不到，再退回
/// 直接同目录 `<install>/updater.exe` 兜底（dev 环境某些临时摆放方式）。
fn locate_updater_exe(app: &AppHandle) -> Result<PathBuf, String> {
    let mut tried: Vec<PathBuf> = Vec::new();

    // 1. resource_dir/binaries/updater.exe —— Tauri 2 NSIS 安装后实际位置
    if let Ok(rdir) = app.path().resource_dir() {
        let candidate = rdir.join("binaries").join("updater.exe");
        if candidate.exists() {
            return Ok(candidate);
        }
        tried.push(candidate);

        // 2. resource_dir/updater.exe —— 备选（如果将来把 updater.exe 直接放根目录）
        let candidate = rdir.join("updater.exe");
        if candidate.exists() {
            return Ok(candidate);
        }
        tried.push(candidate);
    }

    // 3. 跟主 exe 同目录的 binaries/updater.exe（resource_dir 解析异常时兜底）
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let candidate = dir.join("binaries").join("updater.exe");
            if candidate.exists() {
                return Ok(candidate);
            }
            tried.push(candidate);
        }
    }

    log::debug!("updater.exe lookup tried: {tried:?}");
    Err("updater_not_found: updater.exe missing — checked binaries/ + root \
         under resource_dir + install dir (dev 模式正常)"
        .to_string())
}

/// 解析安装目录 = 当前 exe 的父目录。dev 模式下这是 frontend/src-tauri/target/debug/
/// （updater 也不在那，所以前面会先 fail-fast）。
fn install_dir() -> Result<PathBuf, String> {
    let exe = std::env::current_exe()
        .map_err(|e| format!("current_exe failed: {e}"))?;
    exe.parent()
        .map(|p| p.to_path_buf())
        .ok_or_else(|| "current_exe has no parent dir".to_string())
}

/// 给 updater.exe 在 install dir 之外的容身之处。
/// 详细原因见 [`stage_updater_for_run`] 的文档。
fn staged_updater_path(pid: u32) -> PathBuf {
    // 跟 updater/main.py 里 _setup_logging 的 log_dir 同位置：
    // 调试时 staged exe 跟 updater.log 在一起，方便定位。
    std::env::temp_dir()
        .join("csm_update")
        .join(format!("updater-{pid}.exe"))
}

/// 决定 spawn updater 时给它的 cwd。**必须**返回 install dir 之外的路径。
///
/// 为什么：Windows 的进程 cwd 持有目录 handle，如果 updater 自己的 cwd 在
/// install dir 里，那 `os.rename(<install>, <install>.bak)` 必拿 WinError 32。
/// 而 spawn 时不显式设 cwd 的话，子进程会继承父进程（csm-tauri）cwd —— 用户
/// 双击桌面快捷方式启动时 csm-tauri 的 cwd 就是 install dir（NSIS shortcut
/// 默认）。这是 v0.4.x–v0.5.4 一直没修干净的根因。
///
/// 函数抽出来便于单测守住"cwd 永远在 install dir 之外"的 invariant。
fn updater_spawn_cwd() -> PathBuf {
    // %TEMP%（Windows 上是 %LOCALAPPDATA%\Temp\）跟 CSM 默认 install dir
    // (%LOCALAPPDATA%\CSM\) 是同级目录，永远不会嵌套。
    std::env::temp_dir()
}

/// Copy `<install>/binaries/updater.exe` 到 `%TEMP%/csm_update/updater-<pid>.exe`，
/// 返回 staged 路径供 spawn。
///
/// 为什么必须这么做：直接 `spawn <install>/binaries/updater.exe` 时，
/// Windows 把 running updater.exe 映像 mmap 成 image section，持有
/// deny-write/deny-delete handle 直到进程退出。这导致 updater 自己里面
/// `os.rename(<install>, <install>.bak)` 永远拿 WinError 32 失败。
/// taskkill csm-sidecar 只解决了 sidecar 那条锁，但 updater 自己的 image lock
/// 跟 sidecar 无关 —— v0.4.9 → v0.5.1 实测踩坑 (updater.log 留证)。
fn stage_updater_for_run(src: &Path, pid: u32) -> Result<PathBuf, String> {
    let staged = staged_updater_path(pid);
    if let Some(parent) = staged.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("mkdir {parent:?} failed: {e}"))?;
    }
    // 老残留（上次 update 留下的 updater-<pid>.exe）可能还存在并被持有 lock。
    // copy 走 overwrite 语义本身能覆盖，但若旧 staged 还在跑（极少见，前提是
    // 上次没退干净），copy 会因 sharing violation 失败 —— 直接报错让上层
    // surface 出来，比偷偷换名搞副本好。
    std::fs::copy(src, &staged)
        .map_err(|e| format!("copy {src:?} -> {staged:?} failed: {e}"))?;
    Ok(staged)
}

#[tauri::command]
pub async fn install_and_restart(
    app: AppHandle,
    zip_path: String,
) -> Result<(), String> {
    if zip_path.trim().is_empty() {
        return Err("zip_path is empty".to_string());
    }
    let zip = PathBuf::from(&zip_path);
    if !zip.exists() {
        return Err(format!("zip not found: {zip_path}"));
    }

    let updater_exe = locate_updater_exe(&app)?;
    let target = install_dir()?;
    let pid = std::process::id();

    // 关键：把 updater.exe copy 到 install dir 外（%TEMP%）再 spawn。
    // 不这么做，updater 进程映像就锁在它自己要 rename 的目录里，rename
    // 永远拿 WinError 32（v0.4.9 → v0.5.1 实测踩坑，详见 [`stage_updater_for_run`]）。
    let spawn_target = stage_updater_for_run(&updater_exe, pid)?;

    log::info!(
        "install_and_restart: pid={pid} updater={updater_exe:?} staged={spawn_target:?} \
         zip={zip:?} target={target:?}",
    );

    let spawn_cwd = updater_spawn_cwd();
    let mut cmd = Command::new(&spawn_target);
    // CRITICAL — cwd must be **outside** install dir.
    //
    // Without this, the spawned updater inherits csm-tauri's cwd (= install
    // dir on real double-click launches via NSIS shortcuts). The updater's
    // own cwd handle then locks install dir, and the
    // rename(install_dir → backup) step inside replace_directory fails
    // with WinError 32 (the actual root cause of v0.4.x–v0.5.4 hot-update
    // failures; v0.5.1's TEMP-staging of updater.exe only fixed the
    // image-lock side of the problem).
    //
    // updater/main.py also chdir's to TEMP on startup as defense-in-depth.
    cmd.current_dir(&spawn_cwd)
        .arg("--pid")
        .arg(pid.to_string())
        .arg("--zip")
        .arg(&zip)
        .arg("--target")
        .arg(&target);

    // Windows：DETACHED_PROCESS + NEW_PROCESS_GROUP 让 updater 完全脱离主进程
    // 的 console + job object，主进程退出不会带它一起死。
    #[cfg(windows)]
    {
        cmd.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
    }

    log::info!("spawning updater with cwd={spawn_cwd:?}");
    cmd.spawn()
        .map_err(|e| format!("spawn updater failed: {e}"))?;

    // 注意：updater 内部会 wait_for_pid_exit 等几秒，所以这里调 app.exit
    // 后还能把 IPC response 回前端（前端拿到 Ok 之后 webview 已经在被销毁）。
    log::info!("updater spawned, exiting main app");
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;

    #[test]
    fn staged_updater_path_lives_under_system_temp_dir() {
        let p = staged_updater_path(12345);
        assert!(
            p.starts_with(std::env::temp_dir()),
            "{p:?} must live under std::env::temp_dir() so it's outside any install dir"
        );
        let fname = p.file_name().unwrap().to_string_lossy().into_owned();
        assert!(fname.contains("12345"), "filename {fname:?} must encode the pid for parallel-safety");
        assert!(fname.ends_with(".exe"), "{fname:?} must keep .exe extension so Windows treats it as executable");
    }

    #[test]
    fn updater_spawn_cwd_lives_outside_typical_install_dirs() {
        // 守住 v0.5.5 的根因修复：spawn updater 时给的 cwd 绝不能在 install
        // dir 里，否则 updater 自己的 cwd handle 锁死 rename。stable Rust 的
        // Command 没法读 cwd（command_getters 是 nightly），所以这里只能测
        // 抽出来的 updater_spawn_cwd() 这个 invariant。
        //
        // 检查三种典型 install dir：
        //   - NSIS per-user 默认 %LOCALAPPDATA%\CSM\
        //   - Program Files \CSM\
        //   - dev 模式 frontend\src-tauri\target\debug\
        let cwd = updater_spawn_cwd();
        let typical_installs: Vec<PathBuf> = vec![
            std::env::var_os("LOCALAPPDATA")
                .map(PathBuf::from)
                .map(|p| p.join("CSM"))
                .unwrap_or_else(|| PathBuf::from("C:\\NonExistentInstall")),
            std::env::var_os("ProgramFiles")
                .map(PathBuf::from)
                .map(|p| p.join("CSM"))
                .unwrap_or_else(|| PathBuf::from("C:\\NonExistentInstall")),
        ];
        for install in &typical_installs {
            assert!(
                !cwd.starts_with(install),
                "updater_spawn_cwd {cwd:?} unexpectedly inside install dir {install:?}; \
                 if this fires, the v0.5.5 cwd-lock root-cause fix is being undone"
            );
        }
    }

    #[test]
    fn stage_updater_for_run_copies_source_into_temp_and_returns_new_path() {
        // Create a fake "install dir" with an updater.exe inside.
        let fake_install = std::env::temp_dir().join(format!(
            "csm-test-stage-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(fake_install.join("binaries")).unwrap();
        let src = fake_install.join("binaries").join("updater.exe");
        {
            let mut f = fs::File::create(&src).unwrap();
            f.write_all(b"SENTINEL-UPDATER-BYTES").unwrap();
        }

        let pid = 99001;
        let staged = stage_updater_for_run(&src, pid).expect("staging should succeed");

        // 1. staged path must NOT be inside the install dir
        assert!(
            !staged.starts_with(&fake_install),
            "staged path {staged:?} must NOT live inside install dir {fake_install:?} \
             (that's the whole point — running image lock would block rename)"
        );
        // 2. staged file must exist
        assert!(staged.exists(), "staged exe {staged:?} must exist on disk after staging");
        // 3. contents must match the source byte-for-byte
        let staged_bytes = fs::read(&staged).unwrap();
        assert_eq!(staged_bytes, b"SENTINEL-UPDATER-BYTES");

        // cleanup
        let _ = fs::remove_file(&staged);
        let _ = fs::remove_dir_all(&fake_install);
    }
}
