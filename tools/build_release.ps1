param(
    [string]$Version = "v1.1.0"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stagingRoot = Join-Path $projectRoot ".packaging"
$workPath = Join-Path $stagingRoot "work"
$distPath = Join-Path $stagingRoot "dist"
$appPath = Join-Path $distPath "QQJobEditor"
$releasePath = Join-Path $projectRoot "release"
$archivePath = Join-Path $releasePath "QQJobEditor-$Version-win-x64.zip"

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $workPath, $distPath, $releasePath -Force | Out-Null

Push-Location $projectRoot
try {
    python -m unittest discover -s tools -p "test_job_model.py"
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed."
    }

    python -m PyInstaller --noconfirm --clean --workpath $workPath --distpath $distPath QQJobEditor.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    Copy-Item -LiteralPath (Join-Path $projectRoot "assets") -Destination $appPath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "jobs") -Destination $appPath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "platform-tools") -Destination $appPath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $appPath -Force

    $debugPath = Join-Path $appPath "assets\debug"
    if (Test-Path -LiteralPath $debugPath) {
        Remove-Item -LiteralPath $debugPath -Recurse -Force
    }

    $agentBinary = Join-Path $appPath "_internal\MaaAgentBinary\maatouch\universal\maatouch"
    if (-not (Test-Path -LiteralPath $agentBinary)) {
        throw "Packaged MaaAgentBinary is incomplete."
    }

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Compress-Archive -Path $appPath -DestinationPath $archivePath -CompressionLevel Optimal
    Write-Output "Release archive: $archivePath"
}
finally {
    Pop-Location
}
