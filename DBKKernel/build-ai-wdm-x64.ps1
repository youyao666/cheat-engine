[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WdkRoot,

    [Parameter(Mandatory = $true)]
    [string]$VcToolsRoot,

    [string]$WindowsSdkRoot = 'C:\Program Files (x86)\Windows Kits\10',

    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'ai-build\x64'),

    [ValidatePattern('^10\.0\.\d+\.0$')]
    [string]$TargetPlatformVersion = '10.0.26100.0'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-RequiredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description not found: $Path"
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-NativeTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Tool failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

$sourceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$resolvedWdkRoot = Resolve-RequiredPath -Path $WdkRoot -Description 'WDK content root'
$resolvedVcToolsRoot = Resolve-RequiredPath -Path $VcToolsRoot -Description 'MSVC tools root'
$resolvedWindowsSdkRoot = Resolve-RequiredPath -Path $WindowsSdkRoot -Description 'Windows SDK root'
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
$objectDirectory = Join-Path $resolvedOutput 'obj'

$toolDirectory = Resolve-RequiredPath -Path (Join-Path $resolvedVcToolsRoot 'bin\Hostx64\x64') -Description 'MSVC x64 tool directory'
$cl = Resolve-RequiredPath -Path (Join-Path $toolDirectory 'cl.exe') -Description 'C compiler'
$ml64 = Resolve-RequiredPath -Path (Join-Path $toolDirectory 'ml64.exe') -Description 'x64 assembler'
$link = Resolve-RequiredPath -Path (Join-Path $toolDirectory 'link.exe') -Description 'linker'

$vcInclude = Resolve-RequiredPath -Path (Join-Path $resolvedVcToolsRoot 'include') -Description 'MSVC include directory'
$kmInclude = Resolve-RequiredPath -Path (Join-Path $resolvedWdkRoot "Include\$TargetPlatformVersion\km") -Description 'WDK kernel headers'
$kmCrtInclude = Resolve-RequiredPath -Path (Join-Path $resolvedWdkRoot "Include\$TargetPlatformVersion\km\crt") -Description 'WDK kernel CRT headers'
$sharedInclude = Resolve-RequiredPath -Path (Join-Path $resolvedWindowsSdkRoot "Include\$TargetPlatformVersion\shared") -Description 'Windows SDK shared headers'
$umInclude = Resolve-RequiredPath -Path (Join-Path $resolvedWindowsSdkRoot "Include\$TargetPlatformVersion\um") -Description 'Windows SDK user headers'
$ucrtInclude = Resolve-RequiredPath -Path (Join-Path $resolvedWindowsSdkRoot "Include\$TargetPlatformVersion\ucrt") -Description 'Windows SDK UCRT headers'
$kmLibrary = Resolve-RequiredPath -Path (Join-Path $resolvedWdkRoot "Lib\$TargetPlatformVersion\km\x64") -Description 'WDK x64 kernel libraries'

$requiredLibraries = @(
    'BufferOverflowFastFailK.lib',
    'hal.lib',
    'ntoskrnl.lib',
    'ntstrsafe.lib',
    'wmilib.lib'
)
foreach ($library in $requiredLibraries) {
    Resolve-RequiredPath -Path (Join-Path $kmLibrary $library) -Description "WDK library $library" | Out-Null
}

[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
[System.IO.Directory]::CreateDirectory($objectDirectory) | Out-Null

$cSources = @(
    'DBKDrvr.c',
    'DBKFunc.c',
    'debugger.c',
    'deepkernel.c',
    'interruptHook.c',
    'IOPLDispatcher.c',
    'memscan.c',
    'noexceptions.c',
    'processlist.c',
    'threads.c',
    'ultimap.c',
    'ultimap2.c',
    'ultimap2\apic.c',
    'vmxhelper.c',
    'vmxoffload.c'
)

$asmSources = @(
    'amd64\dbkfunca.asm',
    'amd64\debuggera.asm',
    'amd64\noexceptionsa.asm',
    'amd64\ultimapa.asm',
    'amd64\vmxhelpera.asm',
    'amd64\vmxoffloada.asm'
)

$objects = [System.Collections.Generic.List[string]]::new()
$commonCompileArguments = @(
    '/nologo',
    '/c',
    '/TC',
    '/kernel',
    '/Zl',
    '/Zp8',
    '/GS',
    '/Gy',
    '/Oi',
    '/Od',
    '/W3',
    '/WX-',
    '/Zi',
    '/FC',
    '/D_AMD64_',
    '/DAMD64',
    '/D_WIN64',
    '/DRELEASE',
    '/DCEAI_UDL_COMPAT=1',
    '/D_WIN32_WINNT=0x0A00',
    '/DWINVER=0x0A00',
    '/DWINNT=1',
    '/DNTDDI_VERSION=0x0A000010',
    "/I$sourceRoot",
    "/I$kmCrtInclude",
    "/I$kmInclude",
    "/I$sharedInclude",
    "/I$umInclude",
    "/I$ucrtInclude",
    "/I$vcInclude",
    "/Fd$(Join-Path $resolvedOutput 'DBK64.compile.pdb')"
)

foreach ($relativeSource in $cSources) {
    $source = Resolve-RequiredPath -Path (Join-Path $sourceRoot $relativeSource) -Description "driver source $relativeSource"
    $objectName = ($relativeSource -replace '[\\/]', '_') -replace '\.c$', '.obj'
    $object = Join-Path $objectDirectory $objectName
    Write-Host "[cl] $relativeSource"
    Invoke-NativeTool -Executable $cl -Arguments ($commonCompileArguments + @("/Fo$object", $source))
    $objects.Add($object)
}

foreach ($relativeSource in $asmSources) {
    $source = Resolve-RequiredPath -Path (Join-Path $sourceRoot $relativeSource) -Description "driver assembly source $relativeSource"
    $objectName = ($relativeSource -replace '[\\/]', '_') -replace '\.asm$', '.obj'
    $object = Join-Path $objectDirectory $objectName
    Write-Host "[ml64] $relativeSource"
    Invoke-NativeTool -Executable $ml64 -Arguments @('/nologo', '/c', "/Fo$object", $source)
    $objects.Add($object)
}

$target = Join-Path $resolvedOutput 'DBK64.sys'
$pdb = Join-Path $resolvedOutput 'DBK64.pdb'
$map = Join-Path $resolvedOutput 'DBK64.map'
$linkArguments = @(
    '/nologo',
    '/driver',
    '/machine:x64',
    '/subsystem:native,10.00',
    '/entry:GsDriverEntry',
    '/nodefaultlib',
    '/kernel',
    '/dynamicbase',
    '/nxcompat',
    '/debug',
    '/debugtype:cv,fixup',
    '/opt:ref',
    '/opt:icf',
    '/merge:_TEXT=.text',
    '/merge:_PAGE=PAGE',
    '/section:INIT,d',
    "/out:$target",
    "/pdb:$pdb",
    "/map:$map",
    "/libpath:$kmLibrary"
)
$linkArguments += $objects
$linkArguments += $requiredLibraries

Write-Host '[link] DBK64.sys'
Invoke-NativeTool -Executable $link -Arguments $linkArguments

$artifact = Get-Item -LiteralPath $target
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $stream = [System.IO.File]::OpenRead($target)
    try {
        $hashBytes = $sha256.ComputeHash($stream)
    } finally {
        $stream.Dispose()
    }
} finally {
    $sha256.Dispose()
}
$hash = ([BitConverter]::ToString($hashBytes)).Replace('-', '')
$image = [System.IO.File]::ReadAllBytes($target)
if ($image.Length -lt 256 -or [BitConverter]::ToUInt16($image, 0) -ne 0x5A4D) {
    throw 'Linked artifact is not a DOS/PE image'
}
$peOffset = [BitConverter]::ToInt32($image, 0x3C)
if ($peOffset -lt 0 -or ($peOffset + 176) -gt $image.Length -or [BitConverter]::ToUInt32($image, $peOffset) -ne 0x00004550) {
    throw 'Linked artifact has an invalid PE signature'
}
$machine = [BitConverter]::ToUInt16($image, $peOffset + 4)
$optionalHeader = $peOffset + 24
$peMagic = [BitConverter]::ToUInt16($image, $optionalHeader)
$entryPointRva = [BitConverter]::ToUInt32($image, $optionalHeader + 16)
$subsystem = [BitConverter]::ToUInt16($image, $optionalHeader + 68)
$dllCharacteristics = [BitConverter]::ToUInt16($image, $optionalHeader + 70)
$forceIntegrity = ($dllCharacteristics -band 0x0080) -ne 0
if ($machine -ne 0x8664 -or $peMagic -ne 0x020B -or $subsystem -ne 1) {
    throw ("Unexpected PE metadata: machine=0x{0:X4}, magic=0x{1:X4}, subsystem={2}" -f $machine, $peMagic, $subsystem)
}
$signature = Get-AuthenticodeSignature -LiteralPath $target
[pscustomobject]@{
    Path = $artifact.FullName
    Size = $artifact.Length
    Sha256 = $hash
    Signed = $signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid
    SignatureStatus = [string]$signature.Status
    Machine = 'x64'
    MachineCode = ('0x{0:X4}' -f $machine)
    PeMagic = 'PE32+'
    Subsystem = 'Native'
    EntryPointRva = ('0x{0:X8}' -f $entryPointRva)
    DllCharacteristics = ('0x{0:X4}' -f $dllCharacteristics)
    ForceIntegrity = $forceIntegrity
    Target = 'x64 WDM kernel driver'
    TargetPlatformVersion = $TargetPlatformVersion
} | ConvertTo-Json -Depth 3
