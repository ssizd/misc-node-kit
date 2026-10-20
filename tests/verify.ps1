$ErrorActionPreference = "Stop"

$nodeRoot = Split-Path $PSScriptRoot -Parent
$comfyRoot = Split-Path (Split-Path $nodeRoot -Parent) -Parent
$portableRoot = Split-Path $comfyRoot -Parent
$pythonCandidates = @(
    (Join-Path $portableRoot "python_embeded\python.exe"),
    (Join-Path $comfyRoot "venv\Scripts\python.exe")
)

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js was not found on PATH."
}

$python = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    try {
        & $candidate --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $python) {
    throw "No working ComfyUI Python was found. Checked: $($pythonCandidates -join ', ')"
}

Write-Host "Checking frontend JavaScript syntax..."
Get-ChildItem -LiteralPath (Join-Path $nodeRoot "web") -Filter "*.js" -File | ForEach-Object {
    Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName | node --input-type=module --check
    if ($LASTEXITCODE -ne 0) {
        throw "JavaScript syntax check failed: $($_.FullName)"
    }
}

Write-Host "Running JavaScript regression tests..."
Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*_test.mjs" -File | ForEach-Object {
    & node $_.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "JavaScript regression test failed: $($_.FullName)"
    }
}

Write-Host "Running Python regression tests..."
Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*_test.py" -File | ForEach-Object {
    & $python $_.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Python regression test failed: $($_.FullName)"
    }
}

Write-Host "Compiling Python modules..."
$pythonFiles = Get-ChildItem -LiteralPath $nodeRoot -Filter "*.py" -File | Select-Object -ExpandProperty FullName
& $python -m py_compile @pythonFiles
if ($LASTEXITCODE -ne 0) {
    throw "Python compilation failed."
}

Write-Host "All wildcard_image_iterator verification checks passed."
