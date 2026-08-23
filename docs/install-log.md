# 安装记录 · 2026-08-18

## 原先已有

- Git 2.39.5
- Python 3.12.13
- Homebrew
- Docker Desktop 29.4.3（当时 daemon 未开，已 `open -a Docker`）

## 本次完成

- 建目录 `companion-robot/`（config / docs / drivers / src）
- `python3 -m venv .venv` + `pip install -r requirements.txt`
- `docker pull osrf/ros:humble-desktop`（4.82GB，`ros2 --help` 已验证）
- VS Code：直装到 `/Applications/Visual Studio Code.app`，CLI → `~/.local/bin/code`
- Raspberry Pi Imager：直装到 `/Applications/Raspberry Pi Imager.app`

## 未做（需要你账号）

- DeepSeek API Key

## 明确没装（按清单后期才需要）

- 树莓派上的 ROS2 Humble（等板子系统烧好再装）
- smbus2 / gpiozero（树莓派 GPIO，Mac 上无意义）
- STM32 工具链、micro-ROS、RealSense SDK
