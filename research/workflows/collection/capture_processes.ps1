param(
    [string]$InstallRoot = 'C:\Program Files\Deltares\Delft3D FM Suite 2026.02 OpenHMWQ',
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\..\evidence\installation\processes.json')
)
$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\') + '\'
$records = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)
} | ForEach-Object {
    $processRecord = $_
    $modules = @()
    $moduleError = $null
    try {
        $modules = @((Get-Process -Id $processRecord.ProcessId).Modules | Where-Object {
            $_.FileName.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)
        } | Select-Object ModuleName, FileName)
    } catch {
        $moduleError = $_.Exception.Message
    }
    [ordered]@{
        processId = $processRecord.ProcessId
        parentProcessId = $processRecord.ParentProcessId
        name = $processRecord.Name
        executablePath = $processRecord.ExecutablePath
        commandLine = $processRecord.CommandLine
        loadedInstallationModules = $modules
        moduleError = $moduleError
    }
})
$fullOutput = [System.IO.Path]::GetFullPath($OutputPath)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($fullOutput)) | Out-Null
[ordered]@{
    capturedAtUtc = [DateTime]::UtcNow.ToString('o')
    installRoot = $resolvedRoot
    processes = $records
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $fullOutput -Encoding utf8
Write-Output "Captured $($records.Count) processes to $fullOutput"
