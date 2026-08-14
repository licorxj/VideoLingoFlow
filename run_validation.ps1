Write-Host "Validating xiaopai_publish node..." -ForegroundColor Cyan
Set-Location "Y:/VideoLingoLc"
& "backend\venv312\Scripts\activate.ps1"
python validate_node.py
Read-Host "Press Enter to continue"