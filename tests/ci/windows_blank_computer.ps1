# windows_blank_computer.ps1 - CI: install the Social Media Factory the way a real Windows person would.
#
# What it simulates
#   * a ZIP download (git archive = exactly what GitHub's "Download ZIP" contains), not a git clone
#   * unzipped into a folder with a space, an apostrophe and an accented letter
#   * a computer with NO Python, NO git, NO ffmpeg on PATH
#   * Windows PowerShell 5.1 (the old one every Windows has), not PowerShell 7, not Git Bash
#   * a second copy in a deep "OneDrive - Company" style path, which must move its environment
#     somewhere short instead of hitting the Windows 260-character path limit
#
# What it cannot simulate (and the README says so): a locked-down corporate laptop, OneDrive
# placeholder files, antivirus quarantine, and the Claude desktop app itself.
param([Parameter(Mandatory = $true)][string]$Source)

$ErrorActionPreference = "Stop"
$Temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$Accent = [char]0xE9      # built from a code point so this file stays plain ASCII for PowerShell 5.1

function Step($t) { Write-Host ""; Write-Host "=== $t" -ForegroundColor Cyan }
function Must($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

Step "Make the ZIP a person would download"
$Zip = Join-Path $Temp "factory.zip"
git -C $Source archive --format=zip -o $Zip HEAD; Must "git archive"

$Kit = Join-Path $Temp "Joe's Caf$Accent kit"
$Deep = Join-Path $Temp "OneDrive - Some Company Ltd\Documents\Marketing\2026 plans\social-media-factory-main"
foreach ($d in @($Kit, $Deep)) {
    if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Expand-Archive -LiteralPath $Zip -DestinationPath $d -Force
}
Write-Host "kit:  $Kit"
Write-Host "deep: $Deep  ($($Deep.Length) characters)"

Step "Blank computer: strip PATH down to bare Windows"
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
foreach ($p in @("python", "python3", "uv", "git", "ffmpeg")) {
    $found = Get-Command $p -ErrorAction SilentlyContinue
    Write-Host ("  {0,-8} {1}" -f $p, $(if ($found) { $found.Source } else { "none" }))
    if ($found) { throw "$p is still visible; this is not a blank computer" }
}
# The CI image keeps the "py" launcher inside C:\Windows itself, which cannot be taken off PATH.
# The first-run script never calls it, so it is reported, not fatal.
$py = Get-Command py -ErrorAction SilentlyContinue
Write-Host ("  {0,-8} {1}" -f "py", $(if ($py) { "$($py.Source)  (unavoidable on this image; not used)" } else { "none" }))

Step "First run, core tier (no Python on the computer)"
$t0 = Get-Date
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Kit "install\first-run.ps1"); Must "first-run"
Write-Host ("core install: {0:n0}s" -f ((Get-Date) - $t0).TotalSeconds)

$Py = Join-Path $Kit ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) { throw "the Social Media Factory's Python was not created at $Py" }
$Factory = Join-Path $Kit "factory.py"

Step "Second run must skip everything"
$t0 = Get-Date
& $Py $Factory setup; Must "second setup"
$secs = ((Get-Date) - $t0).TotalSeconds
Write-Host ("second run: {0:n0}s" -f $secs)
if ($secs -gt 60) { throw "a repeated setup should be near-instant, took $secs s" }

Step "Status, doctor, unit tests"
& $Py $Factory status; Must "status"
& $Py $Factory doctor; Must "doctor"
Push-Location -LiteralPath $Kit
& $Py -m unittest discover -s tests -t .; Must "unit tests"
Pop-Location

Step "A brand name in another language, read through a pipe"
# The real thing this guards: output captured through a pipe on Windows is written in the console
# code page, which has no Chinese and no emoji, so a brand was created and then saying so crashed.
# Built from code points so this file stays plain ASCII.
$Bakery = [string][char]0x67AB + [char]0x53F6 + " " + [char]::ConvertFromUtf32(0x1F35E)
$env:PYTHONIOENCODING = "cp1252"
$Said = & $Py $Factory new-brand --name $Bakery --id "unicode-check" 2>&1 | Out-String
$Code = $LASTEXITCODE
Remove-Item Env:\PYTHONIOENCODING -ErrorAction SilentlyContinue
if ($Code -ne 0) { Write-Host $Said; throw "a brand named in Chinese with an emoji could not be created (exit $Code)" }
if ($Said -match "Traceback") { Write-Host $Said; throw "creating it printed a traceback" }
Write-Host "  created and reported without a crash"

Step "Video tier, then the deep doctor (video program, codecs, speech model)"
$t0 = Get-Date
& $Py $Factory setup --tier video; Must "video setup"
& $Py $Factory doctor --deep; Must "deep doctor"
Write-Host ("video install + deep doctor: {0:n0}s" -f ((Get-Date) - $t0).TotalSeconds)

Step "Deep OneDrive-style path: the environment must move somewhere short"
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Deep "install\first-run.ps1"); Must "deep first-run"
$State = Get-Content -Raw -LiteralPath (Join-Path $Deep ".factory\state.json") | ConvertFrom-Json
Write-Host "environment: $($State.venv)"
if ($State.venv -notmatch "SocialMediaFactory") { throw "deep path did not relocate its environment: $($State.venv)" }
if (Test-Path -LiteralPath (Join-Path $Deep ".venv")) { throw "a .venv was still created inside the deep path" }
$DeepPy = Join-Path $State.venv "Scripts\python.exe"
$where = & $DeepPy (Join-Path $Deep "factory.py") where; Must "where"
if ($where.Trim() -ne $DeepPy) { throw "factory.py where printed '$where', expected '$DeepPy'" }
& $DeepPy (Join-Path $Deep "factory.py") doctor; Must "deep-path doctor"

Step "What it cost"
function SizeMB($p) { if (Test-Path -LiteralPath $p) { "{0:n0} MB" -f ((Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1MB) } else { "-" } }
Write-Host ("  environment (core+video): " + (SizeMB (Join-Path $Kit ".venv")))
Write-Host ("  installer + state:        " + (SizeMB (Join-Path $Kit ".factory")))
Write-Host ("  page renderer:            " + (SizeMB (Join-Path $env:LOCALAPPDATA "ms-playwright")))
Write-Host ("  speech model:             " + (SizeMB (Join-Path $env:USERPROFILE ".cache\huggingface")))

Write-Host ""
Write-Host "WINDOWS BLANK-COMPUTER TEST PASSED" -ForegroundColor Green
