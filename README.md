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
