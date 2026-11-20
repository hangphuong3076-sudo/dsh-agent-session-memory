param([string]$Python='python')
$ErrorActionPreference='Stop'
$store = Join-Path $env:USERPROFILE '.dsh/storages/agent-session-memory'
$runtime = Join-Path $store 'minilm-runtime'
$folder = if ($env:AGENT_MEMORY_MODEL_DIR) {$env:AGENT_MEMORY_MODEL_DIR} else {Join-Path $store 'models/minilm-l12-q8'}
& $Python (Join-Path $PSScriptRoot "fetch_minilm.py") $folder
if ($LASTEXITCODE -ne 0) {throw "模型文件下载或校验失败"}
$exe = Join-Path $runtime 'Scripts/python.exe'
if (!(Test-Path -LiteralPath $exe)) {
    & $Python -m venv --system-site-packages $runtime
    if ($LASTEXITCODE -ne 0) {throw '创建插件专用 Python 环境失败'}
}
& $exe -m pip --disable-pip-version-check install --only-binary=:all: 'onnxruntime==1.23.2' 'tokenizers==0.22.1'
if ($LASTEXITCODE -ne 0) {throw '安装 CPU 推理组件失败'}
& $exe -c "import numpy,onnxruntime,tokenizers; print('MiniLM CPU runtime:',onnxruntime.__version__,tokenizers.__version__)"
if ($LASTEXITCODE -ne 0) {throw 'CPU 推理组件未能加载'}



