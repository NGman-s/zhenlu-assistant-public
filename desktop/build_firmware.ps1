param(
    [string]$ArduinoCli = '',
    [string]$ArduinoData = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ArduinoCli) {
    $cmd = Get-Command arduino-cli.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { throw '请通过 -ArduinoCli 指定已安装的 arduino-cli.exe 路径。' }
    $ArduinoCli = $cmd.Source
}
if (-not (Test-Path -LiteralPath $ArduinoCli -PathType Leaf)) { throw '找不到 Arduino CLI。' }
if ($ArduinoData) {
    if (-not (Test-Path -LiteralPath $ArduinoData -PathType Container)) { throw 'Arduino 数据目录不存在。' }
    $env:ARDUINO_DIRECTORIES_DATA = (Resolve-Path -LiteralPath $ArduinoData).Path
}
$sketchDir = Join-Path $projectRoot '.tmp\arduino-key'
$buildDir = Join-Path $projectRoot '.tmp\firmware-build'
New-Item -ItemType Directory -Force -Path $sketchDir | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'firmware\device-key\arduino-key\arduino-key.ino') -Destination (Join-Path $sketchDir 'arduino-key.ino') -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'firmware\device-key\main\main.c') -Destination (Join-Path $sketchDir 'device_implementation.h') -Force
& $ArduinoCli compile --fqbn 'esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M' --build-path $buildDir $sketchDir
if ($LASTEXITCODE -ne 0) { throw "固件编译失败（$LASTEXITCODE）。" }
Write-Output "编译完成。输出：$buildDir"
Write-Output '这里只构建文件，不会连接或写入板子。'
