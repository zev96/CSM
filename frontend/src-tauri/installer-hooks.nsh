; CSM NSIS installer hooks.
;
; Tauri 2 reads this file via `bundle.windows.nsis.installerHooks` in
; tauri.conf.json and inlines the macros into its NSIS template. Hooks
; supported:
;   - NSIS_HOOK_PREINSTALL   : before any file is written
;   - NSIS_HOOK_POSTINSTALL  : after install completes
;   - NSIS_HOOK_PREUNINSTALL : before uninstall starts
;   - NSIS_HOOK_POSTUNINSTALL: after uninstall completes
;
; Why this exists: without the PREINSTALL kill, installing on top of a
; running CSM hits "Error opening file for writing" because the running
; csm-sidecar.exe / csm-tauri.exe lock their own image files. NSIS then
; prompts the user with Abort/Retry/Ignore — confusing for non-tech
; users. We kill these processes up front so install can proceed.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Closing any running CSM instance..."
  ; /f = force, /im = by image name. Each returns non-zero if no matching
  ; process — silently fine. nsExec::Exec runs silent (no console flash).
  nsExec::Exec 'taskkill /f /im csm-tauri.exe'
  nsExec::Exec 'taskkill /f /im csm-sidecar.exe'
  nsExec::Exec 'taskkill /f /im updater.exe'

  ; v0.5.5: WebView2 children spawned by csm-tauri can outlive it as
  ; orphans (Tauri 2 doesn't bind them to a Win32 Job Object). They aren't
  ; named csm-* so taskkill above misses them, and their cwd handles on
  ; install dir block NSIS file overwrites that need to delete the old
  ; install. Filter by Tauri identifier "com.csm.app" appearing in cmdline
  ; (the --user-data-dir flag) so we don't kill WebView2 children belonging
  ; to other Tauri/Electron apps the user might have running.
  ;
  ; PowerShell -NoProfile keeps startup fast (~200ms). If PowerShell is
  ; locked down by GPO this is a silent no-op — the kills above still
  ; run, just orphan WebView2 may stay alive (rare enterprise case).
  DetailPrint "Cleaning up orphan WebView2 children..."
  nsExec::Exec 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name = ''msedgewebview2.exe''\" | Where-Object { $_.CommandLine -like ''*com.csm.app*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"'

  ; Bumped from 500ms → 1000ms: WebView2 children take a beat longer to
  ; fully release their cwd / image handles than csm-* on the test
  ; machine where the v0.5.5 root cause was reproduced.
  Sleep 1000
!macroend
