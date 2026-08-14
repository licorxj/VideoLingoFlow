@echo off
echo Validating xiaopai_publish node...
cd /d Y:/VideoLingoLc
call backend\venv312\Scripts\activate.bat
python validate_node.py
pause