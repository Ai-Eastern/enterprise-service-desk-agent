param(
    [string]$BasePython
)

$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))

function Stop-Bootstrap {
    param([string]$Message)
    Write-Error "启动失败：$Message"
    exit 1
}

function Test-Python31011X64 {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    try {
        & $Executable @PrefixArguments -c "import struct, sys; raise SystemExit(0 if sys.version_info[:3] == (3, 10, 11) and struct.calcsize('P') * 8 == 64 else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$baseCommand = $null
$basePrefix = @()

if ($BasePython) {
    if (-not (Test-Path -LiteralPath $BasePython -PathType Leaf)) {
        Stop-Bootstrap "指定的基础解释器不存在：$BasePython"
    }
    $baseCommand = (Resolve-Path -LiteralPath $BasePython).Path
    if (-not (Test-Python31011X64 -Executable $baseCommand)) {
        Stop-Bootstrap "基础解释器必须是 Python 3.10.11 x64：$baseCommand"
    }
}
else {
    $projectPython = Join-Path $ProjectRoot '.tooling\python-3.10.11\python.exe'
    $candidates = @()
    if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
        $candidates += ,@($projectPython, @())
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            $candidates += ,@($command.Source, @())
        }
    }
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        $candidates += ,@($launcher.Source, @('-3.10-64'))
    }

    foreach ($candidate in $candidates) {
        if (Test-Python31011X64 -Executable $candidate[0] -PrefixArguments $candidate[1]) {
            $baseCommand = $candidate[0]
            $basePrefix = $candidate[1]
            break
        }
    }
    if (-not $baseCommand) {
        $runtimeUrl = 'https://api.nuget.org/v3-flatcontainer/python/3.10.11/python.3.10.11.nupkg'
        $runtimeSha512 = '23A600C0BB647698802DA679200FF44C08F4D82B939E109933681A59F9F5DD30D2CAF3EE09118A97598019B6E4D07BD79FFDEA2139405A379BC0AB259178F950'
        $runtimePackage = Join-Path $ProjectRoot '.tmp\python.3.10.11.nupkg'
        $installRoot = Join-Path $ProjectRoot '.tooling\python-3.10.11'
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtimePackage), $installRoot | Out-Null
        Write-Host '未找到 Python 3.10.11 x64，正在从 NuGet 下载 PSF runtime。'
        Invoke-WebRequest -Uri $runtimeUrl -OutFile $runtimePackage
        if ((Get-FileHash -Algorithm SHA512 -LiteralPath $runtimePackage).Hash -ne $runtimeSha512) {
            Stop-Bootstrap "Python runtime SHA512 校验失败：$runtimePackage"
        }
        & tar.exe -xf $runtimePackage -C $installRoot --strip-components 1 tools
        if ($LASTEXITCODE -ne 0) {
            Stop-Bootstrap '解包 Python 3.10.11 x64 runtime 失败。'
        }
        $baseCommand = Join-Path $installRoot 'python.exe'
        if (-not (Test-Python31011X64 -Executable $baseCommand)) {
            Stop-Bootstrap "解包后未发现合格的 Python 3.10.11 x64：$baseCommand"
        }
    }
}

$env:HF_HOME = Join-Path $ProjectRoot '.cache\huggingface'
$env:HF_HUB_CACHE = Join-Path $ProjectRoot '.cache\huggingface\hub'
$env:TRANSFORMERS_CACHE = Join-Path $ProjectRoot '.cache\huggingface\transformers'
$env:SENTENCE_TRANSFORMERS_HOME = Join-Path $ProjectRoot '.cache\sentence-transformers'
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot '.cache\pip'
$env:TEMP = Join-Path $ProjectRoot '.tmp'
$env:TMP = Join-Path $ProjectRoot '.tmp'
$env:PIP_CONFIG_FILE = 'NUL'
Remove-Item Env:PIP_INDEX_URL -ErrorAction SilentlyContinue
Remove-Item Env:PIP_EXTRA_INDEX_URL -ErrorAction SilentlyContinue

foreach ($managedDirectory in @(
    $env:HF_HOME,
    $env:HF_HUB_CACHE,
    $env:TRANSFORMERS_CACHE,
    $env:SENTENCE_TRANSFORMERS_HOME,
    $env:PIP_CACHE_DIR,
    $env:TEMP
)) {
    New-Item -ItemType Directory -Force -Path $managedDirectory | Out-Null
}

$venvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host '未发现 .venv，正在使用 Python 3.10.11 x64 创建项目虚拟环境。'
    & $baseCommand @basePrefix -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) {
        Stop-Bootstrap '创建 .venv 失败。'
    }
}

if (-not (Test-Python31011X64 -Executable $venvPython)) {
    Stop-Bootstrap ".venv 必须使用 Python 3.10.11 x64：$venvPython"
}

Write-Host "基础解释器：$baseCommand $basePrefix"
Write-Host "项目解释器：$venvPython"
Write-Host '正在安装锁定的构建工具。'
& $venvPython -m pip install --disable-pip-version-check --index-url 'https://pypi.org/simple' --no-deps --only-binary=:all: 'pip==24.3.1' 'setuptools==75.6.0' 'wheel==0.45.1'
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '构建工具安装失败。'
}

$pypikaDirectory = Join-Path $ProjectRoot '.tmp\pypika'
$pypikaArchive = Join-Path $pypikaDirectory 'pypika-0.48.9.tar.gz'
$pypikaSha256 = '838836A61747E7C8380CD1B7FF638694B7A7335345D0F559B04B2CD832AD5378'
New-Item -ItemType Directory -Force -Path $pypikaDirectory | Out-Null
Write-Host '正在下载并校验 pypika 0.48.9 sdist。'
& $venvPython -m pip download --disable-pip-version-check --index-url 'https://pypi.org/simple' --no-deps --no-binary=:all: --dest $pypikaDirectory 'pypika==0.48.9'
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pypikaArchive -PathType Leaf)) {
    Stop-Bootstrap 'pypika sdist 下载失败或文件不存在。'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $pypikaArchive).Hash -ne $pypikaSha256) {
    Stop-Bootstrap 'pypika sdist SHA256 校验失败。'
}
& $venvPython -m pip install --disable-pip-version-check --no-deps --no-build-isolation $pypikaArchive
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap 'pypika sdist 安装失败。'
}

Write-Host '正在将锁定 wheel 依赖安装到项目 .venv。'
& $venvPython -m pip install --disable-pip-version-check --index-url 'https://pypi.org/simple' --no-deps --only-binary=:all: --requirement (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '锁定 wheel 依赖安装失败。'
}

& $venvPython (Join-Path $ProjectRoot 'scripts\health_check.py')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '健康检查未通过。'
}

Write-Host '启动检查和健康检查完成。'
exit 0
