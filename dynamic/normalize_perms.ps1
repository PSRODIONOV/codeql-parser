<#
.SYNOPSIS
    Нормализует права доступа (chmod) дерева исходников перед tar/genisoimage.

.DESCRIPTION
    Дерево лежит на NTFS — реальных Unix-прав там нет (или они потеряны при
    копировании через Windows-инструменты). DrvFs без metadata отдаёт
    фиктивные 777 на всё подряд; debhelper трактует control-файлы вида
    debian/*.install с битом +x как СКРИПТ для исполнения, а не статичный
    список — отсюда "Отказано в доступе"/exit 126 при сборке .deb.

    Шаг 1 (список +x) — через Git Bash: её MSYS2-эвристика определяет
    исполняемость по содержимому (shebang/PE-сигнатура), а не по EA-метке.
    WSL для этого не годится: даже с включённой metadata она отдаёт
    permissive-результат для файлов без существующей EA-записи (т.е. для
    ЛЮБОГО файла эталона, если сам эталон не был прежде chmod'нут через
    metadata-aware WSL) — список через WSL получится "все файлы +x".

    Шаг 2 (chmod) — через WSL: реальное сохранение прав на DrvFs работает
    только при включённой metadata (/etc/wsl.conf, [automount]
    options = "metadata", затем wsl --shutdown).

.PARAMETER Reference
    Путь к эталонному дереву (Windows-путь) — откуда берётся список +x.

.PARAMETER Target
    Путь к дереву, которое нужно нормализовать перед упаковкой.

.EXAMPLE
    .\normalize_perms.ps1 -Reference "F:\KSA-src-fact\04981-01-S" -Target "C:\Users\PSRodionov\Desktop\src-gosjava-instr"
#>
param(
    [Parameter(Mandatory = $true)][string]$Reference,
    [Parameter(Mandatory = $true)][string]$Target
)

$ErrorActionPreference = "Stop"

function Find-GitBash {
    $candidates = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LocalAppData\Programs\Git\bin\bash.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Git Bash не найден (искали в Program Files и PATH). Установите Git for Windows."
}

function Convert-ToPosixPath([string]$WinPath) {
    $full = (Resolve-Path $WinPath).Path
    return ($full -replace '\\', '/')
}

function Convert-ToWslPath([string]$WinPath) {
    $full = (Resolve-Path $WinPath).Path
    $drive = $full.Substring(0, 1).ToLower()
    $rest = $full.Substring(2) -replace '\\', '/'
    return "/mnt/$drive$rest"
}

if (-not (Test-Path $Reference)) { throw "Эталонный каталог не найден: $Reference" }
if (-not (Test-Path $Target))    { throw "Целевой каталог не найден: $Target" }

$gitBash         = Find-GitBash
$scriptDir       = $PSScriptRoot
$genListScript   = Join-Path $scriptDir "normalize_perms_genlist.sh"
$applyScript     = Join-Path $scriptDir "normalize_perms_apply.sh"
$tmpList         = [System.IO.Path]::GetTempFileName()

try {
    Write-Host "[1/2] Генерация списка исполняемых файлов из эталона (Git Bash) ..."
    $refPosix      = Convert-ToPosixPath $Reference
    $genListPosix  = Convert-ToPosixPath $genListScript
    $tmpListPosix  = Convert-ToPosixPath $tmpList

    & $gitBash $genListPosix $refPosix $tmpListPosix
    if ($LASTEXITCODE -ne 0) { throw "Генерация списка завершилась с кодом $LASTEXITCODE" }

    Write-Host "[2/2] Применение прав к целевому дереву (WSL) ..."
    $targetWsl   = Convert-ToWslPath $Target
    $tmpListWsl  = Convert-ToWslPath $tmpList
    $applyWsl    = Convert-ToWslPath $applyScript

    wsl bash $applyWsl $targetWsl $tmpListWsl
    if ($LASTEXITCODE -ne 0) { throw "Применение прав завершилось с кодом $LASTEXITCODE" }

    Write-Host "Готово. Можно запускать tar/genisoimage."
}
finally {
    Remove-Item $tmpList -Force -ErrorAction SilentlyContinue
}
