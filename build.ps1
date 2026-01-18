$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectRoot "dist"
$appDistDir = Join-Path $distDir "BulkEmailSender"
$appExePath = Join-Path $distDir "BulkEmailSender.exe"

if (Test-Path $appDistDir) {
  try {
    Remove-Item -Recurse -Force $appDistDir
  } catch {
    throw "Failed to remove '$appDistDir'. Close any running BulkEmailSender.exe and try again. Original error: $($_.Exception.Message)"
  }
}

if (Test-Path $appExePath) {
  try {
    Remove-Item -Force $appExePath
  } catch {
    throw "Failed to remove '$appExePath'. Close any running BulkEmailSender.exe and try again. Original error: $($_.Exception.Message)"
  }
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name "BulkEmailSender" `
  --onefile `
  --console `
  --collect-all pandas `
  --collect-all openpyxl `
  --collect-all fastapi `
  --collect-all uvicorn `
  --collect-all jinja2 `
  --collect-submodules email `
  --hidden-import email.mime.multipart `
  --hidden-import email.mime.base `
  --hidden-import email.mime.text `
  --hidden-import email.utils `
  --hidden-import email.encoders `
  --add-data "$projectRoot\server.py;." `
  --add-data "$projectRoot\email_core.py;." `
  --add-data "$projectRoot\templates;templates" `
  --add-data "$projectRoot\static;static" `
  "$projectRoot\launcher.py"

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete. EXE is in: $projectRoot\dist\BulkEmailSender.exe"
