<#
.SYNOPSIS
    Render .hwpx files to PDF via the Hancom (한글) COM automation object.

.DESCRIPTION
    The COM backend for hwpx.visual.RenderOracle. Reads a JSON job list
    ([{ "src": "...", "pdf": "..." }, ...]) so many file paths (incl. Korean
    names) survive without argument-quoting issues, opens each through
    HWPFrame.HwpObject, exports to PDF, and writes a JSON result array.

    Hancom Office 2022 (v12) exposes Open with a fixed (filename, format, arg)
    signature -- the 1-arg form fails to bind, so pass ("", "") for auto-detect.
    SaveAs(path, "PDF", "") works as-is.

    File access: Hancom asks the user to approve every automated open or save
    of a file outside the user's temporary folder unless a file-path check
    module is registered. Nobody answers that prompt in an automated run, so
    the caller stages every job's "src" and "pdf" under a private folder in
    %TEMP% (WindowsComOracle does). A module registered under
    HKCU\SOFTWARE\HNC\HwpAutomation\Modules is registered here as well, with
    the module type "FilePathCheckDLL"; each result records whether that
    succeeded ("registered").

.PARAMETER Jobs
    Path to the JSON job-list file (UTF-8).

.PARAMETER ResultPath
    Optional path to write the JSON result array to; otherwise written to stdout.
#>
param(
    [Parameter(Mandatory = $true)][string] $Jobs,
    [string] $ResultPath = ""
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Register-FilePathCheck {
    # True when Hancom accepted a file-path check module. The module name is a
    # value name under the Modules key: HWPX_HANCOM_SECURITY_MODULE first, then
    # Hancom's example name, then every other value registered there.
    param($Hwp)
    $names = New-Object System.Collections.Generic.List[string]
    if ($env:HWPX_HANCOM_SECURITY_MODULE) { $names.Add([string]$env:HWPX_HANCOM_SECURITY_MODULE) }
    if (-not $names.Contains("FilePathCheckerModuleExample")) { $names.Add("FilePathCheckerModuleExample") }
    try {
        $key = Get-Item -LiteralPath "HKCU:\SOFTWARE\HNC\HwpAutomation\Modules" -ErrorAction Stop
        foreach ($name in $key.GetValueNames()) {
            if ($name -and -not $names.Contains($name)) { $names.Add($name) }
        }
    } catch {}
    foreach ($name in $names) {
        try {
            if ([bool]$Hwp.RegisterModule("FilePathCheckDLL", $name)) { return $true }
        } catch {}
    }
    return $false
}

$jobList = Get-Content -LiteralPath $Jobs -Raw -Encoding UTF8 | ConvertFrom-Json
$results = New-Object System.Collections.Generic.List[object]
$hwp = $null
try {
    $hwp = New-Object -ComObject "HWPFrame.HwpObject"
    $registered = Register-FilePathCheck $hwp
    # Auto-dismiss modal dialogs so automation never blocks.
    try { $null = $hwp.SetMessageBoxMode(0x00020000) } catch {}

    foreach ($job in $jobList) {
        $src = [string]$job.src
        $pdf = [string]$job.pdf
        $opened = $false; $saved = $false; $err = $null
        try {
            $opened = [bool]$hwp.Open($src, "", "")
            if ($opened) {
                $saved = [bool]$hwp.SaveAs($pdf, "PDF", "")
            }
        } catch {
            $err = $_.Exception.Message
        } finally {
            try { $hwp.Clear(1) | Out-Null } catch {}
        }
        $results.Add([ordered]@{
            src        = $src
            pdf        = $pdf
            opened     = $opened
            saved      = $saved
            error      = $err
            registered = $registered
        })
    }
} finally {
    if ($null -ne $hwp) {
        try { $hwp.Quit() | Out-Null } catch {}
        try { [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($hwp) | Out-Null } catch {}
    }
}

$json = $results | ConvertTo-Json -Depth 5
if ($ResultPath) {
    Set-Content -LiteralPath $ResultPath -Value $json -Encoding UTF8
} else {
    $json
}
