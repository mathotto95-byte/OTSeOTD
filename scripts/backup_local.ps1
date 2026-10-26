param(
    [ValidateSet('Hourly', 'Daily')]
    [string]$Mode = 'Hourly'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $root 'backups_local'
$historyDir = Join-Path $backupDir 'history'
$logFile = Join-Path $backupDir 'backup.log'
$latestFile = Join-Path $backupDir 'ots_otd_latest.json'
$sourceFile = Join-Path $root 'backups\ots_otd_latest.json'
$sourceUrl = 'https://raw.githubusercontent.com/mathotto95-byte/OTSeOTD/main/backups/ots_otd_latest.json'

New-Item -ItemType Directory -Force -Path $historyDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$tempFile = Join-Path $backupDir "download_$stamp.tmp"

try {
    if (Test-Path -LiteralPath $sourceFile) {
        Copy-Item -LiteralPath $sourceFile -Destination $tempFile -Force
    } else {
        Invoke-WebRequest -Uri $sourceUrl -OutFile $tempFile -UseBasicParsing
    }
    $payload = Get-Content -Raw -Path $tempFile | ConvertFrom-Json
    if ($payload.schema -ne 'ots_otd_backup_v1' -or $null -eq $payload.rows) {
        throw 'Arquivo baixado nao e um backup OTS/OTD valido.'
    }

    Copy-Item -LiteralPath $tempFile -Destination $latestFile -Force
    Copy-Item -LiteralPath $tempFile -Destination (Join-Path $historyDir "ots_otd_$stamp.json")
    if ($Mode -eq 'Daily') {
        Copy-Item -LiteralPath $tempFile -Destination (Join-Path $backupDir "ots_otd_diario_$(Get-Date -Format yyyy-MM-dd).json") -Force
    }
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) SUCESSO $Mode registros=$($payload.records)"
}
catch {
    Add-Content -Path $logFile -Value "$(Get-Date -Format o) ERRO $Mode $($_.Exception.Message)"
    exit 1
}
finally {
    Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
}
