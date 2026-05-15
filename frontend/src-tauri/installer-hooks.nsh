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
  ; Give Windows a moment to release the file handles before we start
  ; copying. Without this the first few file writes can still fail on
  ; slow machines.
  Sleep 500
!macroend
