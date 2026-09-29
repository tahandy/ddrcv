# Dependency-free Windows setup tests: powershell -NoProfile -File tests\test_setup.ps1
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\tools\setup.ps1"
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ddrcv setup ' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testRoot | Out-Null
$script:calls = [Collections.Generic.List[object]]::new()
$script:failSync = $false
$script:base = 'c:\python312\python.exe'
$script:uvCalls = 0
$script:passed = 0
function Assert-True($condition, $message) {
    if (-not $condition) { throw $message }
    $script:passed++
}
function Assert-Throws($action, $message) {
    try { & $action } catch {
        Assert-True ($_.ToString() -like "*$message*") "Expected '$message', got $_"
        return
    }
    throw "Expected failure: $message"
}
# Preserve real probe for missing-file behavior before replacing external boundaries.
Assert-Throws { Get-PythonInfo (Join-Path $testRoot 'missing.exe') } 'Python was not found'
function Get-PythonInfo([string]$Executable) {
    if ($Executable -like '*invalid*') { throw 'Unsupported interpreter' }
    $isVenv = $Executable -like '*Scripts\python.exe'
    $base = if ($isVenv) { $script:base } else { $Executable.ToLowerInvariant() }
    return [pscustomobject]@{base=$base; virtual=$isVenv}
}
function Install-Uv([string]$ToolsDirectory) {
    $script:uvCalls++
    return 'fake-uv.exe'
}
function Install-WebView2 { $script:calls.Add(@('webview')) }
function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    $script:calls.Add(@($Arguments))
    if ($Arguments[0] -eq 'venv') {
        New-Item -ItemType Directory -Path $Arguments[-1] | Out-Null
    }
    if ($script:failSync -and $Arguments[0] -eq 'sync') { throw 'simulated sync failure' }
}
try {
    $envDir = Join-Path $testRoot 'managed env'
    $oldEnvironment = $env:UV_PROJECT_ENVIRONMENT
    $env:UV_PROJECT_ENVIRONMENT = 'sentinel'
    Install-DDRCV $testRoot 'desktop' '' $envDir
    Assert-True ($script:calls[0] -contains '--managed-python') 'Default setup must request managed Python'
    Assert-True ($script:calls[0] -contains 'cpython-3.12-windows-x86_64-none') 'Default Python architecture/version'
    $sync = @($script:calls | Where-Object { $_[0] -eq 'sync' })
    Assert-True ($sync.Count -eq 1) 'Setup must sync once'
    Assert-True ($sync[0] -contains '--locked') 'Setup must enforce the lockfile'
    Assert-True ($sync[0] -contains '--inexact') 'Setup must retain unrelated packages'
    Assert-True ($sync[0] -contains (Join-Path $envDir 'Scripts\python.exe')) 'Sync must target the validated venv'
    Assert-True ($env:UV_PROJECT_ENVIRONMENT -eq 'sentinel') 'Environment must be restored'
    Assert-True (@($script:calls | Where-Object { $_ -contains '--provision' }).Count -eq 1) 'Must provision real OCR'

    Assert-True (@($script:calls | Where-Object { $_ -contains 'ddrcv.jacket_lookup' }).Count -eq 0) 'Default setup must not prepare a jacket catalog'
    $script:calls.Clear()
    Install-DDRCV $testRoot 'desktop' '' $envDir -EnableJacketLookup
    $optional = @($script:calls | Where-Object { $_[0] -eq 'sync' })
    Assert-True ($optional[0] -contains 'jacket-lookup') 'Opt-in must request the locked optional extra'
    Assert-True (@($script:calls | Where-Object { $_ -contains 'ddrcv.jacket_lookup' }).Count -eq 2) 'Opt-in must prepare and check the packaged catalog'
    Assert-True (@($script:calls | Where-Object { $_[0] -eq 'venv' }).Count -eq 0) 'Optional patch must reuse the existing environment'
    $script:calls.Clear()
    Install-DDRCV $testRoot 'desktop' '' $envDir -EnableJacketLookup
    Assert-True (@($script:calls | Where-Object { $_[0] -eq 'venv' }).Count -eq 0) 'Repeated optional setup must be idempotent'
    $script:calls.Clear()
    Install-DDRCV $testRoot 'workbench' '' $envDir
    Assert-True (@($script:calls | Where-Object { $_[0] -eq 'venv' }).Count -eq 0) 'Compatible environment must be reused'
    Assert-True (@($script:calls | Where-Object { $_[0] -eq 'webview' }).Count -eq 0) 'Workbench must not install WebView2'

    $script:calls.Clear()
    $script:base = 'c:\custom python\python.exe'
    Install-DDRCV $testRoot 'workbench' $script:base (Join-Path $testRoot 'custom env')
    Assert-True ($script:calls[0] -contains $script:base) 'Must preserve supplied interpreter path as one argument'
    Assert-True ($script:calls[0] -contains '--no-python-downloads') 'Custom Python must disable downloads'

    $before = $script:uvCalls
    Assert-Throws { Install-DDRCV $testRoot 'desktop' 'c:\different\python.exe' $envDir } 'not replace it automatically'
    Assert-True ($before -eq $script:uvCalls) 'Mismatch must fail before downloading or installing'
    Assert-True (Test-Path $envDir) 'Mismatch must preserve existing environment'
    Assert-Throws { Install-DDRCV $testRoot 'desktop' 'invalid.exe' $envDir } 'Unsupported interpreter'

    $script:failSync = $true
    $script:calls.Clear()
    Assert-Throws { Install-DDRCV $testRoot 'desktop' '' $envDir } 'simulated sync failure'
    Assert-True (@($script:calls | Where-Object { $_ -contains '--provision' }).Count -eq 0) 'Failed install must not report readiness'
    Assert-True ($env:UV_PROJECT_ENVIRONMENT -eq 'sentinel') 'Failed setup must restore environment'
    Write-Host "$script:passed setup assertions passed."
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $oldEnvironment
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
