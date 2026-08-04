param(
    [Parameter(Mandatory = $true)]
    [string]$CheatEngineDir
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'ceai_bridge.lua'
$resolvedCeDir = (Resolve-Path -LiteralPath $CheatEngineDir).Path
$autorunDir = Join-Path $resolvedCeDir 'autorun'

if (-not (Test-Path -LiteralPath $source)) {
    throw "Bridge script not found: $source"
}

New-Item -ItemType Directory -Path $autorunDir -Force | Out-Null
$destination = Join-Path $autorunDir 'ceai_bridge.lua'
Copy-Item -LiteralPath $source -Destination $destination -Force

Write-Output "Installed Cheat Engine AI bridge: $destination"
Write-Output 'Restart Cheat Engine to activate the bridge.'
