# No downloads or installations: exercise discovery and the interactive choices.
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\tools\setup.ps1"
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('ddrcv menu ' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $testRoot | Out-Null
$script:passed = 0
$script:answers = [Collections.Generic.Queue[string]]::new()
$script:probed = [Collections.Generic.List[string]]::new()
$script:candidates = @()
$script:base = 'C:\Python312\python.exe'
function Assert-True($condition, $message) {
    if (-not $condition) { throw $message }
    $script:passed++
}
function Read-Host([string]$Prompt) {
    if ($script:answers.Count -eq 0) { throw "Unexpected prompt: $Prompt" }
    return $script:answers.Dequeue()
}
function Choose([string[]]$Answers, [string]$Environment = 'new env') {
    $script:answers.Clear()
    foreach ($answer in $Answers) { $script:answers.Enqueue($answer) }
    $result = Select-SetupPython $testRoot $Environment
    Assert-True ($script:answers.Count -eq 0) 'All expected answers must be consumed'
    return $result
}
function Get-PythonCandidatePaths { return $script:candidates }
function Get-PythonInfo([string]$Executable) {
    $script:probed.Add($Executable)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Missing Python' }
    if ($Executable -like '*unsupported*') { throw 'Unsupported Python version' }
    $virtual = $Executable -like '*\Scripts\python.exe'
    return [pscustomobject]@{base=$(if ($virtual) { $script:base } else { $Executable }); virtual=$virtual}
}
try {
    $valid = Join-Path $testRoot 'Python with spaces\python.exe'
    $unsupported = Join-Path $testRoot 'unsupported.exe'
    $missing = Join-Path $testRoot 'missing.exe'
    New-Item -ItemType Directory -Path (Split-Path $valid -Parent) | Out-Null
    New-Item -ItemType File -Path $valid, $unsupported | Out-Null
    $script:candidates = @($missing, $valid, $valid.ToUpperInvariant(), $unsupported)
    $found = @(Find-CompatiblePython $testRoot)
    Assert-True ($found.Count -eq 1 -and $found[0] -eq $valid) 'Discovery must filter missing/unsupported paths and deduplicate'
    Assert-True (-not $script:probed.Contains($missing)) 'Missing candidates must not be executed'
    Assert-True ($script:probed.Count -eq 2) 'Each existing candidate must be probed only once'

    $result = Choose @('')
    Assert-True ($result.Python -eq '') 'Enter on a fresh install must select local Python'
    $result = Choose @('2', '1')
    Assert-True ($result.Python -eq $valid) 'Detected selection must return the selected interpreter'
    $result = Choose @('3', ('"' + $valid + '"'))
    Assert-True ($result.Python -eq $valid) 'Manual input must accept a quoted path with spaces'
    $result = Choose @('3', (Split-Path $valid -Parent))
    Assert-True ($result.Python -eq $valid) 'Manual input must accept the installation directory'
    $result = Choose @('3', ($valid.Replace($env:TEMP, '%TEMP%')))
    Assert-True ($result.Python -eq $valid) 'Manual input must expand environment variables'
    $result = Choose @('invalid', '3', $missing, '3', $unsupported, '1')
    Assert-True ($result.Python -eq '') 'Invalid input must recover to a valid selection'
    $result = Choose @('2', '999', '2', 'B', '3', '', 'Q')
    Assert-True ($null -eq $result) 'Invalid selection, back, blank manual entry, and cancel must work'

    $script:candidates = @($missing, $unsupported)
    $result = Choose @('2', '1')
    Assert-True ($result.Python -eq '') 'No installations found must allow local installation'
    $existing = Join-Path $testRoot 'existing env'
    New-Item -ItemType Directory -Path (Join-Path $existing 'Scripts') | Out-Null
    New-Item -ItemType File -Path (Join-Path $existing 'Scripts\python.exe') | Out-Null
    $result = Choose @('') $existing
    Assert-True ($result.Python -eq '') 'Enter must reuse an existing compatible environment'
    $result = Choose @('1', 'Q') $existing
    Assert-True ($null -eq $result) 'Local selection must not silently reuse system-based Python'
    Assert-True (Test-Path $existing) 'Existing environment must be preserved'
    $result = Choose @('3', $valid, 'Q') $existing
    Assert-True ($null -eq $result) 'A different selected base Python must not replace an existing environment'
    $script:base = Join-Path $testRoot '.tools\python\cpython-3.12\python.exe'
    $result = Choose @('1') $existing
    Assert-True ($result.Python -eq '') 'Existing local-managed Python may be reused'
    Write-Host "$script:passed menu assertions passed."
} finally {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
