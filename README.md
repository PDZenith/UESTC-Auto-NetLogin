# UESTC Unattended NetLogin (成电无人值守自动联网)
Description:
A robust, unattended network authentication system for UESTC labs. 
Features power-loss recovery, proxy bypass, and Selenium automation. 
Specifically Designed for remote access stability.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

专为 **电子科技大学（UESTC）** 实验室台式机设计的自动联网工具。
解决断电重启、寒假无人值守情况下，校园网网页认证无法自动登录，导致远程控制软件（RayLink/ToDesk/Sunshine）失联的问题。

## ✨ 核心特性

*   **抗代理干扰**：自动屏蔽系统代理（Clash/V2Ray）环境变量，防止开机自启时连接被拒绝。
*   **IP 直连模式**：绕过 DNS 解析，解决刚开机时 `ERR_NAME_NOT_RESOLVED` 问题。
*   **自带环境**：脚本自动下载 Chrome Headless Shell，不依赖系统浏览器版本，杜绝 `SessionNotCreated` 错误。
*   **高鲁棒性**：内置指数重试机制，应对网卡初始化延迟。

## 🚀 快速开始

### 1. 安装
下载本项目代码，在文件夹内打开终端：

```bash
python setup.py
```
*根据提示输入学号和密码，脚本会自动下载所需的 Chrome 驱动并生成 `config.py`。*

### 2. 配置开机自启 (核心步骤)
**必须使用 SYSTEM 账户运行任务，否则受 Windows 密码策略限制无法自启。**

1.  打开 **“任务计划程序”** -> **创建任务**。
2.  **【常规】**：
    *   点击“更改用户或组”，输入 `SYSTEM`，点击确定。
    *   勾选 **“使用最高权限运行”**。
3.  **【触发器】**：新建 -> **“启动时”**。
4.  **【操作】**：
    *   **程序或脚本**：选择本项目目录下的 `run_login.bat`。
    *   **起始于 (Start in)**：⚠️ **必须填写本项目的绝对路径** (例如 `D:\Tools\UESTC-NetLogin\`)。
5.  **【条件】**：**取消勾选** “只有在网络连接可用时才启动”（防止误判）。

### 3. BIOS 设置 (物理防断电)
为了实现“拔线后自动开机”，请进入 BIOS 设置：
*   **MSI 主板**：`Settings` -> `Advanced` -> `Power Management` -> `Restore after AC Power Loss` -> **[Power On]**
*   **ASUS/其他**：寻找 `AC Recovery` 或 `AC Back` 选项并开启。

## ⚠️ 注意事项
*   本项目仅供学习交流，请勿用于非法用途。
*   日志文件会保存在同目录下的 `run_log.txt` 中，方便排查故障。
```

---
