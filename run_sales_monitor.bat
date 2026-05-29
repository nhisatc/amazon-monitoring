@echo off
set PYTHONUTF8=1
cd /d "C:\Users\Admin\OneDrive\Julian\amazon-monitoring"
"C:\Program Files\Python313\python.exe" sales_monitor.py >> "%TEMP%\sales_monitor.log" 2>&1
