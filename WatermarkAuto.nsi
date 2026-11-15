Unicode true
!include "MUI2.nsh"
!include "x64.nsh"

!define VERSION "1.0.0"
!define PACKAGE "dist\WatermarkAuto"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\WatermarkAuto"

Name "WatermarkAuto"
OutFile "dist\WatermarkAuto-Setup-Windows-x64.exe"
InstallDir "$LOCALAPPDATA\Programs\WatermarkAuto"
RequestExecutionLevel user
SetCompressor zlib
ManifestDPIAware true

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "WatermarkAuto"
VIAddVersionKey /LANG=1033 "FileDescription" "WatermarkAuto Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright 2026 Lev-Good"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Hebrew"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "נדרשת מערכת Windows בגרסת 64 סיביות." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd

Section "WatermarkAuto"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  ClearErrors
  File /r "${PACKAGE}\*.*"
  IfErrors install_failed
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  IfErrors install_failed
  CreateShortcut "$SMPROGRAMS\WatermarkAuto.lnk" "$INSTDIR\WatermarkAuto.exe"
  IfErrors install_failed
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "WatermarkAuto"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "Lev-Good"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\WatermarkAuto.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$"$INSTDIR\Uninstall.exe$" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  IfErrors install_failed
  Goto done
  install_failed:
    MessageBox MB_OK|MB_ICONSTOP "ההתקנה נכשלה. יש לסגור את WatermarkAuto ולנסות שוב." /SD IDOK
    SetErrorLevel 2
    Abort
  done:
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\WatermarkAuto.lnk"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  Delete "$INSTDIR\WatermarkAuto.exe"
  Delete "$INSTDIR\ffmpeg.exe"
  Delete "$INSTDIR\START-HERE.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\Licenses"
  RMDir "$INSTDIR"
SectionEnd
