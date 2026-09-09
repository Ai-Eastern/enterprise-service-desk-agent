param(
    [string]$BasePython
)

$ErrorActionPreference = 'Stop'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$env:PYTHONDONTWRITEBYTECODE = '1'

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

function Get-RuntimeContentManifest {
    param([string]$Root)
    $manifestPath = Join-Path $Root 'provenance.json'
    $entries = [System.Collections.Generic.List[string]]::new()
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force | Where-Object { $_.FullName -ne $manifestPath })) {
        $relative = $file.FullName.Substring($Root.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToUpperInvariant()
        $entries.Add("$relative`t$hash")
    }
    $sorted = $entries.ToArray()
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    $bytes = [Text.Encoding]::UTF8.GetBytes([String]::Join("`n", $sorted))
    $digest = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    [pscustomobject]@{ file_count = $sorted.Count; content_manifest_sha256 = [BitConverter]::ToString($digest).Replace('-', '') }
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
    $installRoot = Join-Path $ProjectRoot '.tooling\python-3.10.11'
    $projectPython = Join-Path $installRoot 'python.exe'
    $runtimeManifest = Join-Path $installRoot 'provenance.json'
    $runtimeReady = $false
    if ((Test-Path -LiteralPath $projectPython -PathType Leaf) -and (Test-Path -LiteralPath $runtimeManifest -PathType Leaf)) {
        try {
            $provenance = Get-Content -LiteralPath $runtimeManifest -Raw | ConvertFrom-Json
            $content = Get-RuntimeContentManifest -Root $installRoot
            $runtimeReady = $provenance.source_url -eq 'https://api.nuget.org/v3-flatcontainer/python/3.10.11/python.3.10.11.nupkg' -and
                $provenance.package_sha512 -eq '23A600C0BB647698802DA679200FF44C08F4D82B939E109933681A59F9F5DD30D2CAF3EE09118A97598019B6E4D07BD79FFDEA2139405A379BC0AB259178F950' -and
                $provenance.python_version -eq '3.10.11' -and $provenance.architecture -eq 'x64' -and
                [int]$provenance.file_count -eq $content.file_count -and $provenance.content_manifest_sha256 -eq $content.content_manifest_sha256 -and
                $content.file_count -eq 1712 -and $content.content_manifest_sha256 -eq '755F21CBA88F4C0C4AE12E791732B82F67B6D1EEA9F8A0481BE30DCE0F32AA8C' -and
                (Test-Python31011X64 -Executable $projectPython)
        }
        catch {
            $runtimeReady = $false
        }
    }
    if ($runtimeReady) { $baseCommand = $projectPython }
    if (-not $baseCommand) {
        $runtimeUrl = 'https://api.nuget.org/v3-flatcontainer/python/3.10.11/python.3.10.11.nupkg'
        $runtimeSha512 = '23A600C0BB647698802DA679200FF44C08F4D82B939E109933681A59F9F5DD30D2CAF3EE09118A97598019B6E4D07BD79FFDEA2139405A379BC0AB259178F950'
        $runtimePackage = Join-Path $ProjectRoot '.tmp\python.3.10.11.nupkg.download'
        $stagingRoot = Join-Path (Split-Path -Parent $installRoot) ('python-3.10.11.staging-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $runtimePackage), $stagingRoot | Out-Null
        Write-Host '未找到 Python 3.10.11 x64，正在从 NuGet 下载 PSF runtime。'
        Invoke-WebRequest -Uri $runtimeUrl -OutFile $runtimePackage
        if ((Get-FileHash -Algorithm SHA512 -LiteralPath $runtimePackage).Hash -ne $runtimeSha512) {
            Stop-Bootstrap "Python runtime SHA512 校验失败：$runtimePackage"
        }
        & tar.exe -xf $runtimePackage -C $stagingRoot --strip-components 1 tools
        if ($LASTEXITCODE -ne 0) {
            Stop-Bootstrap '解包 Python 3.10.11 x64 runtime 失败。'
        }
        $stagingPython = Join-Path $stagingRoot 'python.exe'
        if (-not (Test-Python31011X64 -Executable $stagingPython)) {
            Stop-Bootstrap "解包后未发现合格的 Python 3.10.11 x64：$stagingPython"
        }
        & $stagingPython -m ensurepip --version
        if ($LASTEXITCODE -ne 0) {
            Stop-Bootstrap 'Python runtime ensurepip 验证失败。'
        }
        $content = Get-RuntimeContentManifest -Root $stagingRoot
        if ($content.file_count -ne 1712 -or $content.content_manifest_sha256 -ne '755F21CBA88F4C0C4AE12E791732B82F67B6D1EEA9F8A0481BE30DCE0F32AA8C') {
            Stop-Bootstrap 'Python runtime content manifest 校验失败。'
        }
        $provenanceJson = [ordered]@{
            source_url = $runtimeUrl
            package_sha512 = $runtimeSha512
            content_manifest_sha256 = $content.content_manifest_sha256
            file_count = $content.file_count
            python_version = '3.10.11'
            architecture = 'x64'
        } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $stagingRoot 'provenance.json'), $provenanceJson, (New-Object Text.UTF8Encoding($false)))
        $quarantineRoot = $null
        if (Test-Path -LiteralPath $installRoot) {
            $quarantineRoot = Join-Path (Split-Path -Parent $installRoot) ('python-3.10.11.quarantine-' + [guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath $installRoot -Destination $quarantineRoot
        }
        try { Move-Item -LiteralPath $stagingRoot -Destination $installRoot }
        catch {
            if ($quarantineRoot -and (Test-Path -LiteralPath $quarantineRoot)) { Move-Item -LiteralPath $quarantineRoot -Destination $installRoot }
            Stop-Bootstrap 'Python runtime 原子替换失败。'
        }
        $baseCommand = $projectPython
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
Write-Host '正在下载并校验锁定的构建工具。'
$toolDirectory = Join-Path $ProjectRoot '.tmp\bootstrap-tools'
$bootstrapTools = @(
    [pscustomobject]@{ Name = 'pip-24.3.1-py3-none-any.whl'; Url = 'https://files.pythonhosted.org/packages/ef/7d/500c9ad20238fcfcb4cb9243eede163594d7020ce87bd9610c9e02771876/pip-24.3.1-py3-none-any.whl'; Sha256 = '3790624780082365F47549D032F3770EEB2B1E8BD1F7B2E02DACE1AFA361B4ED' }
    [pscustomobject]@{ Name = 'setuptools-75.6.0-py3-none-any.whl'; Url = 'https://files.pythonhosted.org/packages/55/21/47d163f615df1d30c094f6c8bbb353619274edccf0327b185cc2493c2c33/setuptools-75.6.0-py3-none-any.whl'; Sha256 = 'CE74B49E8F7110F9BF04883B730F4765B774EF3EF28F722CCE7C273D253AAF7D' }
    [pscustomobject]@{ Name = 'wheel-0.45.1-py3-none-any.whl'; Url = 'https://files.pythonhosted.org/packages/0b/2c/87f3254fd8ffd29e4c02732eee68a83a1d3c346ae39bc6822dcbcb697f2b/wheel-0.45.1-py3-none-any.whl'; Sha256 = '708E7481CC80179AF0E556BBF0CC00B8444C7321E2700B8D8580231D13017248' }
)
New-Item -ItemType Directory -Force -Path $toolDirectory | Out-Null
$toolArchives = @()
foreach ($tool in $bootstrapTools) {
    $archive = Join-Path $toolDirectory $tool.Name
    Invoke-WebRequest -Uri $tool.Url -OutFile $archive
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $tool.Sha256) {
        Stop-Bootstrap "构建工具 SHA256 校验失败：$($tool.Name)"
    }
    $toolArchives += $archive
}
& $venvPython -m pip install --isolated --cache-dir $env:PIP_CACHE_DIR --no-index --no-deps @toolArchives
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '构建工具安装失败。'
}

$pypikaDirectory = Join-Path $ProjectRoot '.tmp\pypika'
$pypikaArchive = Join-Path $pypikaDirectory 'PyPika-0.48.9.tar.gz'
$pypikaUrl = 'https://files.pythonhosted.org/packages/c7/2c/94ed7b91db81d61d7096ac8f2d325ec562fc75e35f3baea8749c85b28784/PyPika-0.48.9.tar.gz'
$pypikaSha256 = '838836A61747E7C8380CD1B7FF638694B7A7335345D0F559B04B2CD832AD5378'
New-Item -ItemType Directory -Force -Path $pypikaDirectory | Out-Null
Write-Host '正在下载并校验 pypika 0.48.9 sdist。'
Invoke-WebRequest -Uri $pypikaUrl -OutFile $pypikaArchive
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $pypikaArchive).Hash -ne $pypikaSha256) {
    Stop-Bootstrap 'pypika sdist SHA256 校验失败。'
}
& $venvPython -m pip install --isolated --cache-dir $env:PIP_CACHE_DIR --no-index --no-deps --no-build-isolation $pypikaArchive
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap 'pypika sdist 安装失败。'
}

Write-Host '正在将锁定 wheel 依赖安装到项目 .venv。'
& $venvPython -m pip install --isolated --cache-dir $env:PIP_CACHE_DIR --disable-pip-version-check --index-url 'https://pypi.org/simple' --no-deps --only-binary=:all: --require-hashes --requirement (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '锁定 wheel 依赖安装失败。'
}

& $venvPython (Join-Path $ProjectRoot 'scripts\health_check.py')
if ($LASTEXITCODE -ne 0) {
    Stop-Bootstrap '健康检查未通过。'
}

Write-Host '启动检查和健康检查完成。'
exit 0
