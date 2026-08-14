param(
    [string]$Version = "v2.1.0",
    [ValidatePattern('^\.packaging(?:-[A-Za-z0-9._-]+)?$')]
    [string]$StagingName = ".packaging-build",
    [string]$IsccPath = "",
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stagingRoot = Join-Path $projectRoot $StagingName
$workPath = Join-Path $stagingRoot "work"
$stagingDistPath = Join-Path $stagingRoot "dist"
$stagedAppPath = Join-Path $stagingDistPath "Qdd"
$canonicalDistPath = Join-Path $projectRoot "dist"
$canonicalAppPath = Join-Path $canonicalDistPath "Qdd"
$backupAppPath = Join-Path $stagingRoot "previous-app"
$releasePath = Join-Path $projectRoot "release"
$archivePath = Join-Path $releasePath "Qdd-$Version-win-x64.zip"
$setupPath = Join-Path $releasePath "Qdd-$Version-setup.exe"
$installerScriptPath = Join-Path $projectRoot "installer\Qdd.iss"
$portableFlagPath = Join-Path $stagedAppPath "portable.flag"
$setupVersion = $Version -replace '^v', ''
if ($setupVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use vMAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH format."
}

function Resolve-IsccPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (Test-Path -LiteralPath $ExplicitPath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $ExplicitPath).Path
        }
        $explicitCommand = Get-Command -Name $ExplicitPath -ErrorAction SilentlyContinue
        if ($null -ne $explicitCommand -and $explicitCommand.CommandType -eq "Application") {
            return $explicitCommand.Source
        }
        throw "Inno Setup compiler was not found at the explicit -IsccPath value: $ExplicitPath"
    }

    $pathCommand = Get-Command -Name "ISCC.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand) {
        return $pathCommand.Source
    }

    $programFilesRoots = @(
        [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
        [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

    foreach ($programFilesRoot in $programFilesRoots) {
        $candidate = Join-Path $programFilesRoot "Inno Setup 6\ISCC.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    throw "Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup 6 or pass -IsccPath with the compiler path."
}

function Copy-FileTree {
    param(
        [string]$SourceRoot,
        [string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $SourceRoot)) {
        return
    }
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    $resolvedSource = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd("\")
    foreach ($sourceDirectory in Get-ChildItem -LiteralPath $resolvedSource -Recurse -Directory) {
        $relativePath = $sourceDirectory.FullName.Substring($resolvedSource.Length + 1)
        New-Item -ItemType Directory -Path (Join-Path $DestinationRoot $relativePath) -Force | Out-Null
    }
    foreach ($sourceFile in Get-ChildItem -LiteralPath $resolvedSource -Recurse -File) {
        $relativePath = $sourceFile.FullName.Substring($resolvedSource.Length + 1)
        $destinationFile = Join-Path $DestinationRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destinationFile) -Force | Out-Null
        Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationFile -Force
    }
}

function Copy-RuntimeData {
    param(
        [string]$ExistingAppPath,
        [string]$NewAppPath
    )

    $existingJobs = Join-Path $ExistingAppPath "jobs"
    Copy-FileTree -SourceRoot $existingJobs -DestinationRoot (Join-Path $NewAppPath "jobs")

    $existingImageRoot = Join-Path $ExistingAppPath "assets\resource\image"
    $newImageRoot = Join-Path $NewAppPath "assets\resource\image"
    if (-not (Test-Path -LiteralPath $existingJobs) -or -not (Test-Path -LiteralPath $existingImageRoot)) {
        return
    }

    $resolvedImageRoot = (Resolve-Path -LiteralPath $existingImageRoot).Path.TrimEnd("\")
    foreach ($jobFile in Get-ChildItem -LiteralPath $existingJobs -Recurse -File -Filter "*.maa_job.json") {
        try {
            $job = Get-Content -LiteralPath $jobFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            continue
        }
        foreach ($step in @($job.steps)) {
            $template = [string]$step.template
            if ([string]::IsNullOrWhiteSpace($template)) {
                continue
            }
            $relativeTemplate = $template.Replace("/", "\")
            $sourceTemplate = [System.IO.Path]::GetFullPath((Join-Path $resolvedImageRoot $relativeTemplate))
            if (-not $sourceTemplate.StartsWith($resolvedImageRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            if (-not (Test-Path -LiteralPath $sourceTemplate)) {
                continue
            }
            $destinationTemplate = Join-Path $newImageRoot $relativeTemplate
            New-Item -ItemType Directory -Path (Split-Path -Parent $destinationTemplate) -Force | Out-Null
            Copy-Item -LiteralPath $sourceTemplate -Destination $destinationTemplate -Force
        }
    }
}

$resolvedIsccPath = Resolve-IsccPath -ExplicitPath $IsccPath
if (-not (Test-Path -LiteralPath $installerScriptPath -PathType Leaf)) {
    throw "Inno Setup script is missing: $installerScriptPath"
}

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $workPath, $stagingDistPath, $releasePath -Force | Out-Null

Push-Location $projectRoot
try {
    if (-not $SkipChecks) {
        python tools\validate_schema.py
        if ($LASTEXITCODE -ne 0) {
            throw "Schema validation failed."
        }

        $originalQtPlatform = $env:QT_QPA_PLATFORM
        try {
            $env:QT_QPA_PLATFORM = "offscreen"
            python -m unittest discover -s tools -p "test_*.py"
        }
        finally {
            if ($null -eq $originalQtPlatform) {
                Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
            }
            else {
                $env:QT_QPA_PLATFORM = $originalQtPlatform
            }
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Unit tests failed."
        }
    }

    python -m PyInstaller --noconfirm --clean --workpath $workPath --distpath $stagingDistPath Qdd.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    Copy-Item -LiteralPath (Join-Path $projectRoot "assets") -Destination $stagedAppPath -Recurse -Force
    $stagedJobsPath = Join-Path $stagedAppPath "jobs"
    if (Test-Path -LiteralPath $stagedJobsPath) {
        Remove-Item -LiteralPath $stagedJobsPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path (Join-Path $stagedAppPath "jobs") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot "platform-tools") -Destination $stagedAppPath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "README.md") -Destination $stagedAppPath -Force

    $debugPath = Join-Path $stagedAppPath "assets\debug"
    if (Test-Path -LiteralPath $debugPath) {
        Remove-Item -LiteralPath $debugPath -Recurse -Force
    }

    $recordedImagePath = Join-Path $stagedAppPath "assets\resource\image\jobs"
    if (Test-Path -LiteralPath $recordedImagePath) {
        Remove-Item -LiteralPath $recordedImagePath -Recurse -Force
    }

    $agentBinary = Join-Path $stagedAppPath "_internal\MaaAgentBinary\maatouch\universal\maatouch"
    if (-not (Test-Path -LiteralPath $agentBinary)) {
        throw "Packaged MaaAgentBinary is incomplete."
    }

    $stagedJobFiles = @(Get-ChildItem -LiteralPath $stagedJobsPath -Recurse -File)
    if ($stagedJobFiles.Count -ne 0) {
        throw "Release staging jobs directory must be empty."
    }
    if (Test-Path -LiteralPath $recordedImagePath) {
        throw "Release staging must not contain recorded job images."
    }

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    if (Test-Path -LiteralPath $setupPath) {
        Remove-Item -LiteralPath $setupPath -Force
    }

    New-Item -ItemType File -Path $portableFlagPath -Force | Out-Null
    Compress-Archive -Path $stagedAppPath -DestinationPath $archivePath -CompressionLevel Optimal
    Remove-Item -LiteralPath $portableFlagPath -Force
    if (Test-Path -LiteralPath $portableFlagPath) {
        throw "portable.flag must be absent while compiling the installer."
    }

    $isccArguments = @(
        "/DAppVersion=$setupVersion"
        "/DSourceDir=$stagedAppPath"
        "/DOutputDir=$releasePath"
        "/DOutputBaseFilename=Qdd-$Version-setup"
        "/DIconPath=$(Join-Path $projectRoot 'assets\icons\qdd.ico')"
        $installerScriptPath
    )
    & $resolvedIsccPath @isccArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed."
    }
    if (-not (Test-Path -LiteralPath $setupPath -PathType Leaf)) {
        throw "Inno Setup did not create the expected installer: $setupPath"
    }

    New-Item -ItemType File -Path $portableFlagPath -Force | Out-Null

    if (Test-Path -LiteralPath $canonicalAppPath) {
        Copy-RuntimeData -ExistingAppPath $canonicalAppPath -NewAppPath $stagedAppPath
        Move-Item -LiteralPath $canonicalAppPath -Destination $backupAppPath
    }
    New-Item -ItemType Directory -Path $canonicalDistPath -Force | Out-Null
    try {
        Move-Item -LiteralPath $stagedAppPath -Destination $canonicalAppPath
        if (-not (Test-Path -LiteralPath (Join-Path $canonicalAppPath "Qdd.exe"))) {
            throw "Canonical application promotion failed."
        }
        if (Test-Path -LiteralPath $backupAppPath) {
            Remove-Item -LiteralPath $backupAppPath -Recurse -Force
        }
    }
    catch {
        if (Test-Path -LiteralPath $canonicalAppPath) {
            Remove-Item -LiteralPath $canonicalAppPath -Recurse -Force
        }
        if (Test-Path -LiteralPath $backupAppPath) {
            Move-Item -LiteralPath $backupAppPath -Destination $canonicalAppPath
        }
        throw
    }

    Write-Output "Release archive: $archivePath"
    Write-Output "Installer: $setupPath"
    Write-Output "Application: $canonicalAppPath"
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $backupAppPath) {
        Write-Warning "Previous application backup kept at: $backupAppPath"
    }
    elseif (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
