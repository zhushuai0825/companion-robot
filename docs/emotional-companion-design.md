# 情感陪伴机器人设计说明（路遥路线）

## 目标

不是「能聊天的音箱」，而是 **有在场感的陪伴**：

1. **听见** — 连续听、可打断，像真人说话
2. **记得** — 昵称、情绪、未完成心事、约定、上次聊了什么
3. **惦记** — 久别重逢、时段关心（中午别饿着、夜里别熬）
4. **穿过屏幕** — 叮嘱写进备忘录/通知（Mac Agent）
5. **看见你在** — 摄像头粗判画面动静（不假装看清长相）

## 架构

```
麦克风 → Vosk → CompanionBrain(DeepSeek + 人设 + 记忆)
                    ↓
              MiniMax 男声 TTS → CD002 音箱
                    ↓
         可选：<<action:memo>> → Mac desktop_agent
         可选：摄像头 → 在场上下文
```

## 长期记忆

文件：`data/companion_memory.json`

| 字段 | 用途 |
|------|------|
| user_name | 昵称 |
| mood_note | 最近情绪 |
| facts | 工作/家人/爱好等事实 |
| open_loops | 未消化完的心事（可回访） |
| promises | 用户说的约定 |
| session_summaries | 每次会话一句话摘要 |
| last_seen | 上次见面时间 → 久别开场 |

每 8 轮自动摘要；退出时再摘要一次。

## 陪伴节奏（companion_presence.py）

- 48h+ 未见 → 「你回来了」式开场
- 上午/中午/傍晚/深夜 → 不同时段关心
- 连续 8 次没听到说话 → 轻提示「我还在」
- 晚安/再见 → 收束语，不纠缠

## 桌面动作

**Mac 本机**：`osascript` 打开备忘录、写备忘、通知、剪贴板。

**树莓派遥控 Mac**：

```bash
# Mac
export DESKTOP_AGENT_TOKEN=口令
python3 scripts/desktop_agent.py

# Pi src/.env
COMPANION_ACTIONS=1
DESKTOP_AGENT_URL=http://Mac的IP:8765
DESKTOP_AGENT_TOKEN=口令
```

路遥可在回复末加：`<<action:memo:记得喝水>>`

## 摄像头

`vision.enabled: true` 时启动检测画面变化，注入 system：

- 有动静 → 可说「看见你了」，但不描述穿着
- 画面静 → 不假装看清表情

抓拍保存在 `data/vision_latest.jpg`。

## 运行

```bash
# 树莓派完整语音陪伴
python3 src/companion_voice.py

# 文字调试人设
python3 src/companion_chat.py

# 全硬件测试
python3 scripts/test_full_hardware.py
```

## 对标抖音路遥的差异

| 抖音路遥 | 本方案 |
|----------|--------|
| 产品级 ASR/TTS | Vosk + MiniMax |
| 手机 App UI | 树莓派 + 音箱 |
| 厂商记忆云 | 本地 JSON + DeepSeek 提取 |
| 全功能桌面控制 | 白名单动作 + Mac Agent |

下一步可增强：情绪识别（声音/画面）、RAG 范例库、本地微调人设模型。
