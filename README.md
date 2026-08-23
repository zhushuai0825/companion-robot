# companion-robot

对应该站点「机器人学习」第 1 周：本机工具 + 项目骨架。  
路径：`/Users/zhushuai/Downloads/我的项目/companion-robot`

## 本次已安装

| 项 | 状态 |
|----|------|
| 本仓库 + Python 虚拟环境 | 已建 |
| pytest / allure-pytest / pytest-rerunfailures / edge-tts / opencv / openai | 已装进 `.venv` |
| Docker Desktop | 本来就有，已启动 |
| `osrf/ros:humble-desktop` | 已拉取（约 4.8GB） |
| Visual Studio Code 1.133 | `/Applications/Visual Studio Code.app`，命令 `code` |
| Raspberry Pi Imager 2.0.10 | `/Applications/Raspberry Pi Imager.app` |

你还需要自己做的一件事：到 [DeepSeek 开放平台](https://platform.deepseek.com/) 建 API Key，复制 `.env.example` 为 `.env` 后填入。

## 用法

```bash
cd "/Users/zhushuai/Downloads/我的项目/companion-robot"
source .venv/bin/activate
pytest --version
```

ROS2（Mac 不原生安装，走 Docker）：

```bash
docker run -it --rm osrf/ros:humble-desktop bash
# 容器内
ros2 --help
```

当前镜像是 linux/amd64，在 Apple Silicon 上会走模拟，第一次稍慢，能跑即可。

烧树莓派系统：打开 **Raspberry Pi Imager** → Raspberry Pi 5 → Raspberry Pi OS 64-bit → 齿轮填 WiFi / 用户 / 打开 SSH。

## 情感陪伴（路遥路线）

- 人设配置：`config/companion.yaml` + 固定圣经 `config/persona_luoyao.yaml`
- 人设配置：`config/companion.yaml` + 固定圣经 `config/persona_luoyao.yaml`（全局写入 system prompt）
- 微调训练集（仅导出用，运行时不用）：`data/dialogue_examples.jsonl`
- 长期记忆：`data/companion_memory.json`（事实 / 开放情绪 / 约定 / 摘要）
- 文字试聊：`python3 src/companion_chat.py`
- 语音陪伴：`python3 src/companion_voice.py`
- 微调导出：`python3 scripts/export_finetune_dataset.py`
- 路线图：`docs/persona-model-roadmap.md`
