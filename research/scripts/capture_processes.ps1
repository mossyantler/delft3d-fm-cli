param([string]$InstallRoot, [string]$OutputPath)
& (Join-Path $PSScriptRoot '../workflows/collection/capture_processes.ps1') @PSBoundParameters
