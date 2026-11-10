# Windows USB 连接原型

这是供开发验证的原型，不是硬件授权或防复制系统，不适用于真实患者数据。支持按 VID/PID 检测 Windows 设备，或使用已登记公钥验证设备签名。VID/PID 可复制，检测到设备不等于验证身份，正式使用需要独立密钥、设备认证、服务端授权等机制。

## 准备

在项目根目录的 PowerShell 中，先按根目录 README 安装后端依赖，再构建前端：

```powershell
cd frontend
npm install
npm run build
cd ..
```

先按根目录 README 配置 Fun-ASR 和千问，再使用下文的 USB 检测或签名验证命令启动。默认端口为 8765，可用 `--port 8766` 调整。

拔出后页面显示断开，后端拒绝新的处理和确认操作；在默认 30 秒宽限期内允许保存已编辑草稿或手动问诊内容，已有请求继续处理。本地服务随后停止接收新请求，等待已开始的请求结束后退出；浏览器页面不会自动关闭。若内容仍未保存，页面关闭或电脑断电后可能丢失。宽限期内重新插入可恢复，关闭后重新插入会重新启动服务。

当前是命令行开发程序，运行期间窗口需保持开启，不会自动安装、下载更新或开机自启。原有开发模式仍可按根目录 README 启动，不受此原型限制。

## 获取 ESP32 后检测设备

将设备插入后，可在 PowerShell 查看 Windows 识别到的 USB 设备：

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\VID_' } | Select-Object FriendlyName, Status, InstanceId
```

找到目标设备的 `VID_XXXX&PID_YYYY`，将以下示例替换为实际值：

```powershell
.\backend\.venv\Scripts\python.exe .\desktop\agent.py --usb --vid XXXX --pid YYYY
```

实际板卡的 USB 接口、芯片、驱动以及插拔稳定性尚未测试。部分开发板通过 USB 转串口芯片连接，检测到的可能是转换芯片而非 ESP32 身份。设备标识是检测条件，并非授权证明；检测失败或设备消失时按断开处理。退出使用 Ctrl+C。

## 后续工作

- 根据实际开发板验证枚举信息、插拔、重连和断电恢复，再确定设备协议。
- 实现设备挑战应答和服务端许可，设计密钥生产、撤销与换机流程。
- 完成正式安装包、代码签名、更新与开机自启；完成本地接口和数据安全设计。
- 在真实患者试点前完成账号、权限隔离、隐私与审计等必要工作。

## ESP32-S3 身份验证开发原型

新增的设备固件和连接程序使用 P-256 公钥与每次全新的随机挑战。设备首次运行时在 NVS 中生成密钥，电脑端登记公钥后验证签名；每次重新验证均生成新挑战，失败、设备断开或公钥不匹配时不会启动受该模式管理的服务。

**状态：开发原型，不是可用于交付的授权或防复制方案。** 固件把私钥存储在普通 NVS，不保证不可导出；公钥登记依赖本机人工核对，电脑端和本地状态可被修改；没有服务器授权、设备撤销、登录或可信生产登记。真实部署需单独设计安全启动、硬件密钥保护、身份注册、服务端授权及恢复流程。在未取得用户许可和确认型号、闪存布局、备份方式前，不向板子写入固件或修改 eFuse。

Arduino 框架在检测到 NVS 不兼容或空间不足时可能自动擦除该分区；更换固件或重置 NVS 可能丢失设备密钥及原有配置。开发原型不应存放实际患者信息。

电脑端依赖安装：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r .\desktop\requirements.txt
```

固件源代码在 `firmware/device-key`。Windows 可使用现有 Arduino CLI 和 ESP32 开发包构建；也保留了尚未经完整构建验证的 ESP-IDF 工程。构建本身不写入板子。固件仅针对板载 USB Serial/JTAG 接口开发，不支持 USB 转串口接口。

本机已安装 Arduino IDE 2.3.6、ESP32 开发包 3.3.11 和 esptool 5.3.1。本机重新构建命令如下（其他电脑需要使用各自的安装路径）：

```powershell
.\desktop\build_firmware.ps1 -ArduinoCli 'E:\app\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe' -ArduinoData 'D:\CDrive_Moved\Users\SHISHAOKAI\AppData\Local\Arduino15'
```

通用的 ESP32-S3 开发板配置只用于编译测试，烧录前必须确认板卡型号、闪存容量、分区和现有程序的备份与恢复方式。构建输出放在 `.tmp/firmware-build`。

取得明确授权并成功刷入后，在项目根目录先查看公钥指纹，再由可信流程核验并人工确认登记：

```powershell
.\backend\.venv\Scripts\python.exe .\desktop\device_identity.py fingerprint --com COM4
.\backend\.venv\Scripts\python.exe .\desktop\device_identity.py enroll --com COM4 --confirm <完整指纹>
.\backend\.venv\Scripts\python.exe .\desktop\device_identity.py verify --com COM4
.\backend\.venv\Scripts\python.exe .\desktop\agent.py --identity --com COM4 --port 8766
```

`<完整指纹>` 是需要实际替换的占位符，不要照搬；登记文件默认放在 `desktop/device-public.der`，若文件已存在则拒绝覆盖。COM 端口可能变化。没有可用签名固件或已登记公钥时，验证模式会失败，不会自动回退到只检查 VID/PID 的模式。

运行电脑端验证：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q desktop/tests
```
