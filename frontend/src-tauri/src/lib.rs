//! Tauri shell library entry. Keeping the actual `tauri::Builder` setup
//! here lets `main.rs` stay tiny (just `csm_tauri_lib::run()`), which is
//! what the Tauri 2 mobile templates expect.
mod sidecar;
mod tray;
mod updater;

use sidecar::SidecarState;
use tauri::{Manager, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Single-instance must be the FIRST plugin so a duplicate launch
        // is intercepted before any other init runs.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            log::info!("second instance launched — focusing main window");
            tray::show_main(app);
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        // fs 插件 —— 前端通过 dialog.save() 选保存路径后，用 fs.writeFile
        // 把 CSV bytes 写到磁盘（替代浏览器 <a download> 自动下载到
        // Downloads 目录无提示的旧路径）。
        .plugin(tauri_plugin_fs::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .targets([
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                        file_name: Some("csm-shell".into()),
                    }),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Webview),
                ])
                .level(log::LevelFilter::Info)
                .max_file_size(5_000_000) // 5 MB before rotate
                .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepAll)
                .build(),
        )
        .manage(SidecarState::default())
        .setup(|app| {
            // System tray — wired before the sidecar so the icon is
            // already visible during the slow sidecar boot on cold start.
            if let Err(e) = tray::setup(&app.handle()) {
                log::error!("tray setup failed: {e}");
            }
            if let Err(e) = sidecar::spawn_sidecar(&app.handle()) {
                log::error!("sidecar spawn failed: {e}");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            sidecar::get_sidecar,
            updater::install_and_restart,
        ])
        .on_window_event(|window, event| match event {
            // Intercept the X-button so closing the window minimises to
            // tray instead of exiting. User must use Tray → 退出 to fully
            // quit. Mirrors the legacy PyQt tray behaviour.
            WindowEvent::CloseRequested { api, .. } => {
                let _ = window.hide();
                api.prevent_close();
            }
            // Final cleanup: when the window is *actually* destroyed
            // (e.g. via app.exit() from the tray menu), kill the
            // sidecar so the loopback port is freed for the next launch.
            WindowEvent::Destroyed => {
                let app = window.app_handle().clone();
                tauri::async_runtime::block_on(async move {
                    app.state::<SidecarState>().kill().await;
                });
            }
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("error while running CSM Tauri shell");
}
