//! System tray (Tauri 2 API).
//!
//! Behaviour mirrors the legacy PyQt tray:
//! - Left-click the icon → toggle main window visibility
//! - Right-click the icon → context menu with: 显示主窗口 / 退出
//! - Closing the main window minimises to tray (handled in lib.rs)
//!
//! Quit through the menu is the only way to actually shut the app down;
//! the X on the window is intercepted as a hide.
//!
//! ## Menu styling note
//!
//! Tauri's `Menu` API delegates rendering to the OS — on Windows that's
//! the standard right-click menu chrome (white bg, system font, system
//! shadow). We can't paint it with the app's beige theme without giving
//! up the native menu and building a custom transparent webview window
//! at the cursor. For now we polish what we can within the native API:
//! a disabled brand header, a separator, accelerator hints, and grouped
//! items so the menu at least feels "designed" rather than the default
//! 2-row stub.
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};

pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    // Disabled brand header — gives the menu a "title" so the user knows
    // which app this menu belongs to. `enabled=false` greys it out so it's
    // not click-able and reads as a label.
    let header = MenuItem::with_id(
        app,
        "header",
        "Content SEO Maker",
        false,
        None::<&str>,
    )?;

    // Show / hide the main window. Accelerator is a hint shown on the
    // right side of the menu item — the actual key binding lives in the
    // global shortcut layer (not wired yet; the hint is forward-looking).
    let show_item = MenuItem::with_id(
        app,
        "show",
        "显示主窗口",
        true,
        Some("Ctrl+Shift+C"),
    )?;

    // Quit. Native menus on Windows render Alt+F4-style accelerator on
    // the right; we use the more familiar Ctrl+Q which Office/Tauri apps
    // commonly bind. Same caveat — global shortcut not wired yet.
    let quit_item = MenuItem::with_id(
        app,
        "quit",
        "退出 CSM",
        true,
        Some("Ctrl+Q"),
    )?;

    let sep1 = PredefinedMenuItem::separator(app)?;
    let sep2 = PredefinedMenuItem::separator(app)?;

    let menu = Menu::with_items(
        app,
        &[&header, &sep1, &show_item, &sep2, &quit_item],
    )?;

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
            // "header" is disabled so it shouldn't fire, but explicitly
            // ignore it to avoid future warnings if Tauri changes that.
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
