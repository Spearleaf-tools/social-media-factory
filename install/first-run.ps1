# first-run.ps1 - for a Windows computer that has NO Python at all.
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File install\first-run.ps1
#
# It downloads one small installer program (uv) INTO this folder, then lets it fetch a private
# Python and run the normal setup. No admin rights. Nothing is added to PATH. Delete this folder
# and what it installed here is gone.
#
# If the computer already has Python 3.8+, you do not need this: run  python factory.py setup

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $Here ".factory\bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$Uv = Join-Path $Bin "uv.exe"

if (-not (Test-Path $Uv)) {
    Write-Host "Downloading the installer program into this folder..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $env:UV_UNMANAGED_INSTALL = $Bin
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Host "The download was blocked or failed: $($_.Exception.Message)"
        Write-Host "On a work computer, IT may need to allow astral.sh and github.com."
        Write-Host "Or install Python 3.12 from https://www.python.org/downloads/ and run: python factory.py setup"
        exit 1
    }
}

Set-Location $Here
& $Uv run --no-project --python 3.12 factory.py setup @args
exit $LASTEXITCODE
