; The customer-cloud edition supersedes the legacy internal desktop edition.
; Only the exact, per-user legacy install location is removed. The normal
; Tauri upgrade flow separately replaces an older customer-cloud installation.
!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$LOCALAPPDATA\短视频复刻工作台\uninstall.exe" legacy_internal_present legacy_internal_done

legacy_internal_present:
  ExecWait '"$LOCALAPPDATA\短视频复刻工作台\uninstall.exe" /S' $0

legacy_internal_done:
!macroend
