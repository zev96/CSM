//! System tray (Tauri 2 API).
//!
//! Behaviour mirrors the legacy PyQt tray:
//! - Left-click the icon → toggle main window visibility
//! - Right-click the icon → context menu: 显示主窗口 / 退出
//! - Closing the main window minimises to tray (handled in lib.rs)
//!
//! Quit through the menu is the only way to actually shut the app down;
//! the X on the window is intercepted as a hide.
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "退出 CSM", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

    let _tray = TrayIconBuilder::with_id("csm-tray")
        .icon(app.default_window_icon().cloned().unwrap())
        .tooltip("CSM · Content SEO Maker")
        .menu(&menu)
        .on_menu_event(move |app, event| match event.id.as_ref() {
            "show" => {
                show_main(app);
            }
            "quit" => {
                // Best-effort: ask sidecar to exit cleanly first, then
                // quit the Tauri runtime. lib.rs's on_window_event won't
                // fire for app.exit() so we kill the sidecar here too.
                let app_clone = app.clone();
                tauri::async_runtime::spawn(async move {
                    let state = app_clone.state::<crate::sidecar::SidecarState>();
                    state.kill().await;
                    app_clone.exit(0);
                });
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left click toggles. Right click is consumed by the menu.
            if let TrayIconEvent::Click { button, button_state, .. } = event {
                if button == MouseButton::Left && button_state == MouseButtonState::Up {
                    let app = tray.app_handle();
                    if let Some(win) = app.get_webview_window("main") {
                        let visible = win.is_visible().unwrap_or(false);
                        if visible {
                            let _ = win.hide();
                        } else {
                            let _ = win.show();
                            let _ = win.set_focus();
                        }
                    }
                }
            }
        })
        .build(app)?;

    Ok(())
}

pub fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}
