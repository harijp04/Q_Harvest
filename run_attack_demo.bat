@echo off
cd /d "%~dp0"
echo Starting a 20-second controlled UDP traffic burst to your default gateway...
python frontend\attack_sim.py dos 20
pause
