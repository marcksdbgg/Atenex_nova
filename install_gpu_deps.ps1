#!/usr/bin/env pwsh
# install_gpu_deps.ps1
# Run after torch+cu128 finishes installing.
# Installs the full project + ML dependencies in the .venv312 GPU venv.

Set-Location $PSScriptRoot

$python = "backend\.venv312\Scripts\python.exe"

Write-Host "=== Installing project dependencies in .venv312 (Python 3.12 + CUDA) ==="

# Install the base project + dev extras from backend/
Write-Host "`n[1/3] pip install -e '.[all]'..."
& $python -m pip install -e "backend[all]" 2>&1

# Install turbovec
Write-Host "`n[2/3] Installing turbovec..."
& $python -m pip install turbovec==0.7.0 2>&1

# Verify GPU is visible
Write-Host "`n[3/3] Verifying CUDA..."
& $python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'); print('Torch:', torch.__version__)"

Write-Host "`n=== Done. Use backend\.venv312\Scripts\python.exe for all GPU workloads. ==="
