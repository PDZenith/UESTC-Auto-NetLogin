# UESTC Auto NetLogin

面向电子科技大学校园网无人值守 Windows 主机的自动认证与断线恢复工具。它以
SYSTEM 计划任务运行，在公网已经可用时立即退出；只有确认离线后才启动项目内固定
版本的 Headless Chrome 登录校园网。

## 可靠性保护

- 使用 Microsoft Connect Test 和备用 204 端点严格判断公网状态。
- 通过源地址绑定代理访问校园网认证服务器，绕过 Clash/Mihomo TUN 的 Fake-IP
  和错误路由。
- 支持当前有线入口 `10.253.0.237` 的动态“校园网登录”按钮，并兼容旧入口。
- 验证码可见时禁止提交；明确的凭据错误不会循环尝试。
- 登录后只有重新通过公网探测才记录成功。
- 文件锁和任务的 `IgnoreNew` 策略共同防止并行登录。
- Python、Chrome Headless Shell 和 ChromeDriver 均使用项目内固定路径。
- 计划任务支持开机延迟执行、每分钟巡检、失败重试和四分钟执行上限。

## 安全说明

`config.py` 保存校园网账号与密码，并已被 `.gitignore` 排除。不要提交真实凭据、
运行日志、缓存、备份目录或 `state/`。复制示例文件开始配置：

```powershell
Copy-Item .\config.example.py .\config.py
```

然后仅在本机编辑 `config.py`：

```python
USER_ID = "your-student-id"
PASSWORD = "your-campus-network-password"
```

## 安装

系统要求：Windows 10/11、Python 3.13，以及管理员 PowerShell。

```powershell
Set-Location D:\NetLogin
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe .\setup.py
```

`setup.py` 会下载配套的 Chrome Headless Shell 与 ChromeDriver
`133.0.6943.53`。如果 `config.py` 尚不存在，它还会提示创建本地配置。

先执行安全探测，它不会读取或提交凭据：

```powershell
.\run_login.bat --probe-only
```

确认探测成功后，在管理员 PowerShell 注册 SYSTEM Watchdog：

```powershell
.\Install-WatchdogTask.ps1
```

安装程序不会主动启动任务或重启计算机。运行日志默认写入
`D:\NetLogin\run_log.txt`。

## Clash/Mihomo TUN

如果 TUN 将校园网认证地址送往代理节点，应在最终 `MATCH,PROXY` 之前添加：

```yaml
- IP-CIDR,10.253.0.0/16,DIRECT,no-resolve
```

不要仅依赖 `DOMAIN-SUFFIX,uestc.edu.cn,DIRECT`，因为认证入口使用 IP 地址时不会
命中域名规则。程序自身仍保留源地址绑定作为独立保护。

## 验证与排障

```powershell
# 自动测试
.\.venv\Scripts\python.exe -m pytest -q --import-mode=importlib .\tests\test_my_login.py

# 查看最近日志
Get-Content .\run_log.txt -Tail 80

# 检查计划任务
Get-ScheduledTask -TaskName UESTC-NetLogin-Watchdog
Get-ScheduledTaskInfo -TaskName UESTC-NetLogin-Watchdog
```

主要退出码：`0` 成功或已在线，`10` 配置错误，`20` 浏览器资源错误，`30` 无兼容
入口，`40` 验证码，`41` 凭据拒绝，`42` 提交后未恢复公网，`50` 未预期错误。

## 验证状态

当前版本已在有线校园网、Clash Verge TUN 开启的条件下完成真实注销与自动恢复：
程序识别 `.237` 登录页、提交凭据并在首次公网复核时确认恢复。冷启动、BIOS 来电
开机和具体远程控制软件仍应在目标机器上分别验收。

## License

[MIT](LICENSE)
