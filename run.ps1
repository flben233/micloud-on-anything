$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
python -X utf8 (Join-Path $root "pipeline.py") @args
exit $LASTEXITCODE
