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
use std::path::PathBuf;
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

    log::info!(
        "install_and_restart: pid={pid} updater={updater_exe:?} zip={zip:?} target={target:?}",
    );

    let mut cmd = Command::new(&updater_exe);
    cmd.arg("--pid")
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

    cmd.spawn()
        .map_err(|e| format!("spawn updater failed: {e}"))?;

    // 注意：updater 内部会 wait_for_pid_exit 等几秒，所以这里调 app.exit
    // 后还能把 IPC response 回前端（前端拿到 Ok 之后 webview 已经在被销毁）。
    log::info!("updater spawned, exiting main app");
    app.exit(0);
    Ok(())
}
