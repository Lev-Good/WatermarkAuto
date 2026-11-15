@echo off
setlocal
cd /d "%~dp0"
python -c "import sys, tkinter; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.11 or later with Tcl/Tk and add it to PATH.
    pause
    exit /b 1
)
if exist "ffmpeg.exe" goto launch
if exist ".watermark-deps\imageio_ffmpeg\binaries\ffmpeg-*.exe" goto launch
where ffmpeg.exe >nul 2>&1
if not errorlevel 1 goto launch
echo Installing FFmpeg locally. This step requires internet access.
python -m pip --disable-pip-version-check install --upgrade --target ".watermark-deps" --only-binary=:all: imageio-ffmpeg==0.6.0
if errorlevel 1 (
    echo Unable to install FFmpeg. You can place ffmpeg.exe in this folder and try again.
    pause
    exit /b 1
)
:launch
start "" pythonw.exe "%~dp0watermark_app.pyw"
