@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt "pyinstaller>=6,<7"
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name YTD3 --collect-all imageio_ffmpeg --collect-all pytubefix --collect-all nodejs_wheel YTdownloader.py
if errorlevel 1 goto fail
echo.
echo Build complete. Share the ENTIRE dist\YTD3 folder as a ZIP.
echo Your friends should extract the ZIP and open YTD3.exe.
pause
exit /b 0
:fail
echo Build failed. See the error above. Install Python 3.11 or newer from python.org if needed.
pause
exit /b 1
