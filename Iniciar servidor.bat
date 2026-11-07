@echo off
chcp 65001 >nul
title Control Remoto PC
cd /d "%~dp0"
where py >nul 2>nul && (py -3 server.py %*) || (python server.py %*)
pause
