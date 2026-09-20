# Shared Windows installer. Dot-source to load functions without running setup.
[CmdletBinding()]
param(
    [ValidateSet('desktop', 'workbench')][string]$App = 'desktop',
    [string]$Python,
    [string]$Venv = '.venv',
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

function Get-PythonInfo {
    param([string]$Executable)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Python was not found at '$Executable'. Pass the full path to python.exe."
    }
    $probe = @'
import json, os, platform, struct, sys
print(json.dumps(dict(version=list(sys.version_info[:2]), bits=struct.calcsize('P')*8, implementation=platform.python_implementation(), machine=platform.machine(), base=os.path.normcase(os.path.realpath(sys._base_executable)), virtual=sys.prefix != sys.base_prefix)))
'@
    $result = & $Executable -I -c $probe
    if ($LASTEXITCODE -ne 0) { throw "Cannot run Python at '$Executable'." }
    $info = $result | ConvertFrom-Json
    if (($info.version -join '.') -ne '3.12' -or $info.bits -ne 64 -or
        $info.implementation -ne 'CPython' -or $info.machine -ne 'AMD64') {
        throw "'$Executable' must be 64-bit x64 CPython 3.12. Other versions are not validated with this dependency set."
    }
    return $info
}

function Assert-Environment {
    param([string]$Directory, [string]$SelectedPython)
    $selected = $null
    if ($SelectedPython) { $selected = Get-PythonInfo $SelectedPython }
    if (Test-Path -LiteralPath $Directory) {
        $exe = Join-Path $Directory 'Scripts\python.exe'
        try {
            $existing = Get-PythonInfo $exe
            if (-not $existing.virtual) { throw 'This directory is not a virtual environment.' }
            if ($selected -and $selected.base -ne $existing.base) {
                throw "It was created from '$($existing.base)', not '$($selected.base)'."
            }
        } catch {
            throw "Cannot reuse '$Directory': $_ Close DDRCV, rename that environment as a backup, and rerun setup. Setup will not replace it automatically."
        }
    }
}

function Get-PythonCandidatePaths {
    param([string]$Root)
    # Only inspect common install locations, not the user's entire disk.
    $parents = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, ($env:SystemDrive + '\'))
    if ($env:LOCALAPPDATA) { $parents += Join-Path $env:LOCALAPPDATA 'Programs\Python' }
    foreach ($parent in $parents) {
        if ($parent -and (Test-Path -LiteralPath $parent -PathType Container)) {
            Get-ChildItem -LiteralPath $parent -Directory -Filter 'Python*' -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName 'python.exe' }
        }
    }
    $managedRoots = @(Join-Path $Root '.tools\python')
    if ($env:LOCALAPPDATA) { $managedRoots += Join-Path $env:LOCALAPPDATA 'uv\python' }
    if ($env:APPDATA) { $managedRoots += Join-Path $env:APPDATA 'uv\python' }
    if ($env:USERPROFILE) {
        $managedRoots += Join-Path $env:USERPROFILE '.local\share\uv\python'
        foreach ($name in @('python', 'python312')) {
            Join-Path $env:USERPROFILE "scoop\apps\$name\current\python.exe"
        }
    }
    foreach ($parent in $managedRoots) {
        if (Test-Path -LiteralPath $parent -PathType Container) {
            Get-ChildItem -LiteralPath $parent -Directory -Filter 'cpython-3.12*' -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName 'python.exe' }
        }
    }
    foreach ($registry in @('HKCU:\Software\Python\PythonCore',
                             'HKLM:\Software\Python\PythonCore',
                             'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        if (Test-Path $registry) {
            foreach ($version in (Get-ChildItem $registry -ErrorAction SilentlyContinue)) {
                $install = Get-Item (Join-Path $version.PSPath 'InstallPath') -ErrorAction SilentlyContinue
                if ($install) {
                    $executable = $install.GetValue('ExecutablePath')
                    if ($executable) { $executable }
                    $directory = $install.GetValue('')
                    if ($directory) { Join-Path $directory 'python.exe' }
                }
            }
        }
    }
    Get-Command python.exe, python3.exe, python3.12.exe -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\*' } |
        ForEach-Object { $_.Source }
}

function Find-CompatiblePython {
    param([string]$Root)
    $seen = @{}
    foreach ($candidate in (Get-PythonCandidatePaths $Root)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $path = (Resolve-Path -LiteralPath $candidate).ProviderPath
        if ($seen.ContainsKey($path)) { continue }
        $seen[$path] = $true
        try {
            $null = Get-PythonInfo $path
            $path
        } catch {
            # Missing/broken/unsupported installations do not become menu choices.
            Write-Verbose "Skipping '$path': $_"
        }
    }
}

function Select-SetupPython {
    param([string]$Root, [string]$Environment)
    if (-not [IO.Path]::IsPathRooted($Environment)) { $Environment = Join-Path $Root $Environment }
    $exists = Test-Path -LiteralPath $Environment
    $default = if ($exists) { '4' } else { '1' }
    while ($true) {
        Write-Host ''
        Write-Host 'DDRCV desktop setup' -ForegroundColor Cyan
        Write-Host "Application environment: $Environment"
        Write-Host 'Requires 64-bit CPython 3.12. Choose how to get Python:'
        Write-Host '  1. Install/use local Python in this checkout'
        Write-Host '  2. Choose an existing Python from common install locations'
        Write-Host '  3. Enter a Python path manually'
        if ($exists) { Write-Host '  4. Reuse the current application environment' }
        Write-Host '  Q. Cancel'
        $choice = (Read-Host "Selection [$default]").Trim()
        if (-not $choice) { $choice = $default }
        if ($choice -ieq 'q') { return $null }
        $selected = ''
        if ($choice -eq '1') {
            # A local-Python selection must not silently reuse a system-based venv.
            if ($exists) {
                try {
                    $existing = Get-PythonInfo (Join-Path $Environment 'Scripts\python.exe')
                    $localRoot = [IO.Path]::GetFullPath((Join-Path $Root '.tools\python')) + '\'
                    if (-not $existing.base.StartsWith($localRoot, [StringComparison]::OrdinalIgnoreCase)) {
                        throw 'This environment uses another Python. Choose 4 to reuse it, or rename the environment as a backup and rerun setup to install local Python.'
                    }
                } catch {
                    Write-Host $_ -ForegroundColor Yellow
                    continue
                }
            }
        } elseif ($choice -eq '2') {
            Write-Host 'Checking installed Pythons...'
            $found = @(Find-CompatiblePython $Root)
            if ($found.Count -eq 0) {
                Write-Host 'No compatible Python found. Choose local installation or enter a path.' -ForegroundColor Yellow
                continue
            }
            for ($i = 0; $i -lt $found.Count; $i++) { Write-Host "  $($i + 1). $($found[$i])" }
            Write-Host '  B. Back'
            $index = 0
            $answer = (Read-Host 'Python number').Trim()
            if ($answer -ieq 'b') { continue }
            if (-not [int]::TryParse($answer, [ref]$index) -or $index -lt 1 -or $index -gt $found.Count) {
                Write-Host 'Enter a number from the list.' -ForegroundColor Yellow
                continue
            }
            $selected = $found[$index - 1]
        } elseif ($choice -eq '3') {
            $answer = (Read-Host 'Path to python.exe (or its folder); leave blank to go back').Trim().Trim('"').Trim("'")
            if (-not $answer) { continue }
            $selected = [Environment]::ExpandEnvironmentVariables($answer)
            if (Test-Path -LiteralPath $selected -PathType Container) { $selected = Join-Path $selected 'python.exe' }
        } elseif ($choice -ne '4' -or -not $exists) {
            Write-Host 'Choose one of the listed options.' -ForegroundColor Yellow
            continue
        }
        try {
            Assert-Environment $Environment $selected
            if ($selected) { $selected = (Resolve-Path -LiteralPath $selected).ProviderPath }
        } catch {
            Write-Host $_ -ForegroundColor Yellow
            continue
        }
        return [pscustomobject]@{ Python = $selected }
    }
}

function Install-Uv {
    param([string]$ToolsDirectory)
    $version = '0.10.12'
    $destination = Join-Path $ToolsDirectory "uv-$version"
    $exe = Join-Path $destination 'uv.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        Write-Host "Downloading uv $version from Astral..."
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        $installer = Join-Path $destination 'install.ps1'
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/$version/install.ps1" -OutFile $installer
        $env:UV_UNMANAGED_INSTALL = $destination
        Invoke-Checked 'powershell.exe' @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer)
    }
    $reported = & $exe --version
    if ($LASTEXITCODE -ne 0 -or $reported -notmatch "^uv $([regex]::Escape($version))( |$)") {
        throw "Unexpected uv installation in '$destination'. Rename that folder and retry."
    }
    return $exe
}

function Install-WebView2 {
    param([string]$Interpreter, [string]$ToolsDirectory)
    & $Interpreter -B -c 'from webview.platforms.winforms import _is_chromium; raise SystemExit(0 if _is_chromium() else 1)'
    if ($LASTEXITCODE -eq 0) { return }
    Write-Host 'Installing Microsoft Edge WebView2 Runtime for the desktop panel...'
    $installer = Join-Path $ToolsDirectory 'MicrosoftEdgeWebview2Setup.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation,') {
        throw 'The WebView2 download did not have a valid Microsoft signature.'
    }
    $process = Start-Process -FilePath $installer -ArgumentList '/silent', '/install' -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "WebView2 installation failed (exit $($process.ExitCode)). Install Microsoft Edge WebView2 Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ and rerun setup."
    }
}

function Install-DDRCV {
    param([string]$Root, [string]$Application, [string]$Interpreter, [string]$Environment)
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'DDRCV requires 64-bit Windows.' }
    if (-not [IO.Path]::IsPathRooted($Environment)) { $Environment = Join-Path $Root $Environment }
    # Validate before downloading or changing an existing environment.
    Assert-Environment $Environment $Interpreter
    $toolsDirectory = Join-Path $Root '.tools'
    $variables = @('UV_UNMANAGED_INSTALL', 'UV_PYTHON_INSTALL_DIR', 'UV_PYTHON_INSTALL_REGISTRY',
                   'UV_PYTHON_BIN_DIR', 'UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'UV_LINK_MODE')
    $saved = @{}
    foreach ($name in $variables) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
    $oldTls = [Net.ServicePointManager]::SecurityProtocol
    Push-Location $Root
    try {
        [Net.ServicePointManager]::SecurityProtocol = $oldTls -bor [Net.SecurityProtocolType]::Tls12
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $toolsDirectory 'python'
        $env:UV_PYTHON_BIN_DIR = Join-Path $toolsDirectory 'bin'
        $env:UV_PYTHON_INSTALL_REGISTRY = '0'
        $env:UV_PROJECT_ENVIRONMENT = $Environment
        $env:UV_CACHE_DIR = Join-Path $toolsDirectory 'cache'
        $env:UV_LINK_MODE = 'copy'
        $uv = Install-Uv $toolsDirectory
        $venvPython = Join-Path $Environment 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $Environment)) {
            if ($Interpreter) {
                Write-Host "Creating environment from $Interpreter..."
                Invoke-Checked $uv @('venv', '--seed', '--python', $Interpreter, '--no-python-downloads', $Environment)
            } else {
                Write-Host 'Creating environment with a local, managed Python 3.12 (downloaded if needed)...'
                Invoke-Checked $uv @('venv', '--seed', '--managed-python', '--python', 'cpython-3.12-windows-x86_64-none', $Environment)
            }
        }
        Assert-Environment $Environment $Interpreter
        Write-Host 'Installing DDRCV and its locked dependencies...'
        Invoke-Checked $uv @('sync', '--locked', '--inexact', '--no-dev', '--extra', $Application,
                            '--python', $venvPython, '--no-python-downloads')
        # Native file dialogs are part of both applications.
        Invoke-Checked $venvPython @('-I', '-c', "import tkinter; t = tkinter.Tcl(); print('Tkinter ready: ' + t.eval('info patchlevel'))")
        if ($Application -eq 'desktop') { Install-WebView2 $venvPython $toolsDirectory }
        $renderer = Join-Path (Split-Path $Root -Parent) 'ddr_score_render'
        if ((Test-Path (Join-Path $renderer 'pyproject.toml')) -or (Test-Path (Join-Path $renderer 'setup.py'))) {
            Invoke-Checked $uv @('pip', 'install', '--python', $venvPython, '--no-deps', '--editable', $renderer)
        } else {
            Write-Host 'Optional ddr_score_render not found. You can select its folder in the app later.'
        }
        Invoke-Checked $venvPython @('-B', '-m', 'ddrcv.ocr.check', '--provision')
        Invoke-Checked $venvPython @('-B', '-m', "ddrcv.$Application", '--check')
        Write-Host ''
        Write-Host "Setup complete. Environment: $Environment" -ForegroundColor Green
        if ([IO.Path]::GetFullPath($Environment) -eq [IO.Path]::GetFullPath((Join-Path $Root '.venv'))) {
            if ($Application -eq 'desktop') { Write-Host 'Double-click launch_desktop.vbs to start DDRCV.' }
            else { Write-Host 'Double-click launch_workbench.bat to start the rehearsal panel.' }
        } else {
            Write-Host "Launch with: & '$venvPython' -B -m ddrcv.$Application"
        }
    } finally {
        Pop-Location
        [Net.ServicePointManager]::SecurityProtocol = $oldTls
        foreach ($name in $variables) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $root = Split-Path $PSScriptRoot -Parent
        if ($App -eq 'desktop' -and -not $Python -and -not $NonInteractive) {
            if ([Console]::IsInputRedirected) {
                throw 'Interactive setup needs a terminal. Use -NonInteractive for automatic setup, or pass -Python with an interpreter path.'
            }
            $selection = Select-SetupPython $root $Venv
            if ($null -eq $selection) {
                Write-Host 'Setup cancelled. No installation changes were made.'
                exit 0
            }
            $Python = $selection.Python
        }
        Install-DDRCV -Root $root -Application $App -Interpreter $Python -Environment $Venv
        exit 0
    } catch {
        Write-Host "Setup failed: $_" -ForegroundColor Red
        Write-Host 'Correct the error above and rerun setup. Close DDRCV before changing its environment.'
        exit 1
    }
}
