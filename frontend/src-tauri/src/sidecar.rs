//! Sidecar process management.
//!
//! Lifecycle:
//! 1. `spawn_sidecar` is called from `setup` and forks `csm-sidecar`
//!    via the tauri-plugin-shell `Command::new_sidecar(...)` API.
//! 2. We read the first line of the child's stdout — that is the
//!    handshake JSON `{"port":..., "token":..., "version":1}` written by
//!    `csm_sidecar.lifespan.emit_handshake`.
//! 3. The handshake is stored in a `tauri::State` so the JS side can
//!    pull it via `invoke('get_sidecar')`.
//! 4. On app exit, the child is killed (Tauri's CommandChild keeps the
//!    handle for us; we just call `kill()`).
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{Mutex, OnceCell};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SidecarHandshake {
    pub port: u16,
    pub token: String,
    pub version: u32,
}

#[derive(Default)]
pub struct SidecarState {
    handshake: Mutex<Option<SidecarHandshake>>,
    child: Mutex<Option<CommandChild>>,
}

impl SidecarState {
    pub async fn set_child(&self, child: CommandChild) {
        let mut g = self.child.lock().await;
        *g = Some(child);
    }
    pub async fn set_handshake(&self, h: SidecarHandshake) {
        let mut g = self.handshake.lock().await;
        *g = Some(h);
    }
    pub async fn handshake(&self) -> Option<SidecarHandshake> {
        self.handshake.lock().await.clone()
    }
    pub async fn kill(&self) {
        if let Some(child) = self.child.lock().await.take() {
            // Best-effort. If sidecar is already dead, ignore the error.
            let _ = child.kill();
        }
    }
}

/// Notifies any tasks awaiting the handshake — used to make
/// `get_sidecar` block until we've actually parsed it.
static HANDSHAKE_READY: OnceCell<Arc<tokio::sync::Notify>> = OnceCell::const_new();

async fn notify() -> Arc<tokio::sync::Notify> {
    HANDSHAKE_READY
        .get_or_init(|| async { Arc::new(tokio::sync::Notify::new()) })
        .await
        .clone()
}

/// Spawn the bundled `csm-sidecar` binary, parse the handshake JSON,
/// and store it on the app's `SidecarState`.
pub fn spawn_sidecar(app: &AppHandle) -> Result<(), String> {
    let app_handle = app.clone();
    let cmd = app
        .shell()
        .sidecar("csm-sidecar")
        .map_err(|e| format!("sidecar binary not found: {e}"))?;

    let (mut rx, child) = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

    tauri::async_runtime::spawn(async move {
        let state = app_handle.state::<SidecarState>();
        state.set_child(child).await;

        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let line_str = String::from_utf8_lossy(&line).to_string();
                    if state.handshake().await.is_none() {
                        match serde_json::from_str::<SidecarHandshake>(line_str.trim()) {
                            Ok(h) => {
                                log::info!(
                                    "sidecar handshake received: port={} version={}",
                                    h.port, h.version,
                                );
                                state.set_handshake(h).await;
                                notify().await.notify_waiters();
                            }
                            Err(e) => {
                                log::warn!("sidecar stdout pre-handshake (unparsed): {line_str:?} ({e})");
                            }
                        }
                    } else {
                        // Anything after the handshake is just noisy logs from the
                        // sidecar process — uvicorn writes its own to stderr but
                        // user code might still print here. Forward to log so we
                        // don't lose it.
                        log::debug!("sidecar stdout: {line_str}");
                    }
                }
                CommandEvent::Stderr(line) => {
                    let line_str = String::from_utf8_lossy(&line).to_string();
                    log::debug!("sidecar stderr: {line_str}");
                }
                CommandEvent::Error(err) => log::error!("sidecar IO error: {err}"),
                CommandEvent::Terminated(payload) => {
                    log::warn!(
                        "sidecar terminated (code={:?}, signal={:?})",
                        payload.code, payload.signal,
                    );
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Tauri command: returns the handshake once it's ready.
/// Awaiting this from JS lets `useSidecar.bootstrap()` retry cleanly.
#[tauri::command]
pub async fn get_sidecar(state: State<'_, SidecarState>) -> Result<SidecarHandshake, String> {
    if let Some(h) = state.handshake().await {
        return Ok(h);
    }
    // Wait up to 10s for the sidecar to come up. Beyond that we give up
    // and return an error so the UI can render a diagnostic page.
    let n = notify().await;
    let waited = tokio::time::timeout(std::time::Duration::from_secs(10), n.notified()).await;
    if waited.is_err() {
        return Err("sidecar handshake timed out after 10s".into());
    }
    state
        .handshake()
        .await
        .ok_or_else(|| "handshake notify fired but state still empty".into())
}
