; The customer-cloud edition supersedes the legacy internal desktop edition.
; Only the exact, per-user legacy install location is removed. The normal
; Tauri upgrade flow separately replaces an older customer-cloud installation.
!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$LOCALAPPDATA\短视频复刻工作台\uninstall.exe" legacy_internal_present legacy_internal_done

legacy_internal_present:
  ClearErrors
  ExecWait '"$LOCALAPPDATA\短视频复刻工作台\uninstall.exe" /S' $0
  IfErrors legacy_internal_failed
  IntCmp $0 0 legacy_internal_done legacy_internal_failed legacy_internal_failed

legacy_internal_failed:
  MessageBox MB_ICONSTOP|MB_OK "旧版短视频复刻工作台卸载失败。为避免两个版本并存，本次安装已中止；请先手动卸载旧版后重试。"
  Abort

legacy_internal_done:
!macroend
