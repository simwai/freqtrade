@echo off
rem Stops any leftover server.py, then launches the server in a new
rem visible console window. The server's stdout+stderr is captured to
rem %TEMP%\lab-server.log; the window stays open (cmd /K) and shows the
rem exit code + log path on exit, so a crash never silently disappears.
rem Extra args pass through, e.g.: lab-open.bat --port 8090
setlocal
set "ROOT=%~dp0..\.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PY=%ROOT%\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
rem kill leftover server.py instances (any port)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'user_data[\\\\/]+scripts[\\\\/]+server\.py' } | ForEach-Object { Write-Host ('Stopping old lab server (pid ' + $_.ProcessId + ')'); Stop-Process -Id $_.ProcessId -Force }"
rem write a tiny launcher script in the user's temp dir - avoids the
rem cmd /K quoting hell when the python or script path contains spaces.
rem the script cds to the dashboard scripts dir first so the .venv shim
rem finds the project interpreter. The launcher:
rem   - runs python with -u (unbuffered) so log output streams
rem   - captures stdout+stderr to %TEMP%\lab-server.log
rem   - echoes the exit code and log path on exit, then pauses
rem This way the cmd /K window stays open even on failure, and the user
rem can read the log instead of staring at a closed window.
set "LAUNCH=%TEMP%\lab-server-launcher-%RANDOM%.bat"
set "LABLOG=%TEMP%\lab-server.log"
>  "%LAUNCH%" echo @echo off
>> "%LAUNCH%" echo cd /d "%~dp0"
>> "%LAUNCH%" echo "%PY%" -u "%~dp0server.py" %*  ^> "%LABLOG%" 2^>^&1
>> "%LAUNCH%" echo.
>> "%LAUNCH%" echo --- lab server exited with code %ERRORLEVEL% ---
>> "%LAUNCH%" echo Log file: %LABLOG%
>> "%LAUNCH%" echo (Press any key to close this window)
>> "%LAUNCH%" pause ^>nul
rem open a new visible console window running the launcher. The bat
rem itself exits as soon as the window is open.
start "Strategy Lab server" cmd.exe /K "%LAUNCH%"
endlocal
