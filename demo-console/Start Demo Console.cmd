@echo off
title VelocityFraud Live Demo Console
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python server.py %*) else (py -3 server.py %*)
if errorlevel 1 pause
