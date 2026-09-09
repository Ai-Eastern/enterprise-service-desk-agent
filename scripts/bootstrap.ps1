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

function Test-Python311X64 {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    try {
        & $Executable @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else 1)" 2>$null
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
    if (-not (Test-Python311X64 -Executable $baseCommand)) {
        Stop-Bootstrap "基础解释器必须是 Python 3.11 x64：$baseCommand"
    }
}
else {
    $projectPython = Join-Path $ProjectRoot '.tooling\conda-py311\python.exe'
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
        $candidates += ,@($launcher.Source, @('-3.11'))
    }

    foreach ($candidate in $candidates) {
        if (Test-Python311X64 -Executable $candidate[0] -PrefixArguments $candidate[1]) {
            $baseCommand = $candidate[0]
            $basePrefix = $candidate[1]
            break
        }
    }
    if (-not $baseCommand) {
        Stop-Bootstrap '未找到可用的 Python 3.11 x64。可通过 -BasePython 指定解释器。'
    }
}

$env:HF_HOME = Join-Path $ProjectRoot '.cache\huggingface'
$env:HF_HUB_CACHE = Join-Path $ProjectRoot '.cache\huggingface\hub'
$env:TRANSFORMERS_CACHE = Join-Path $ProjectRoot '.cache\huggingface\transformers'
$env:SENTENCE_TRANSFORMERS_HOME = Join-Path $ProjectRoot '.cache\sentence-transformers'
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot '.cache\pip'
$env:TEMP = Join-Path $ProjectRoot '.tmp'
$env:TMP = Join-Path $ProjectRoot '.tmp'

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
    Write-Host '未发现 .venv，正在使用 Python 3.11 x64 创建项目虚拟环境。'
    & $baseCommand @basePrefix -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) {
        Stop-Bootstrap '创建 .venv 失败。'
    }
}

if (-not (Test-Python311X64 -Executable $venvPython)) {
    Stop-Bootstrap ".venv 必须使用 Python 3.11 x64：$venvPython"
}

Write-Host "基础解释器：$baseCommand $basePrefix"
Write-Host "项目解释器：$venvPython"
Write-Host '正在将锁定依赖安装到项目 .venv。'
& $venvPython -m pip install --disable-pip-version-check --requirement (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '依赖安装失败，请检查当前 PowerShell 进程的网络和 pip 配置。'
}

& $venvPython (Join-Path $ProjectRoot 'scripts\health_check.py')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '健康检查未通过。'
}

& $venvPython (Join-Path $ProjectRoot 'scripts\generate_demo_data.py')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '虚构数据生成失败。'
}

& $venvPython (Join-Path $ProjectRoot 'scripts\ingest.py')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap 'Chroma 入库失败。若模型下载失败，可仅在当前 PowerShell 进程设置 $env:HF_ENDPOINT="https://hf-mirror.com" 后重试。'
}

Write-Host '启动检查、虚构数据生成和 Chroma 入库完成。'
exit 0
