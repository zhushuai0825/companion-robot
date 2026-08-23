# 桌面操作能力（路遥「帮你打开备忘录」）

抖音路遥除对话外，可 **把叮嘱写进你能看见的地方**（备忘录、便签等）。这是情感体验的重要一环。

## 现状

- 树莓派 `companion_voice.py`：**仅语音 + 文字**，不能操作手机/电脑。
- 文案层已支持「把叮嘱写进备忘录」这种说法；执行需另接能力。

## 推荐架构

```mermaid
flowchart LR
  Brain[CompanionBrain] -->|<<action:open_memo>>| Agent[Desktop Agent]
  Agent --> Mac[Mac 备忘录 / 便签]
  Agent --> Phone[手机 快捷指令]
```

## Mac 最小实现（下一步）

在 Mac 上跑 `companion_chat.py` 时，解析回复中的动作标签：

| 标签 | 行为 |
|------|------|
| `<<action:open_memo>>` | `osascript` 打开备忘录 |
| `<<action:memo:正文>>` | 写入一条新备忘 |

环境变量 `COMPANION_ACTIONS=1` 开启；树莓派默认关闭。

## 手机

- iOS：快捷指令 + HTTP 回调
- Android：类似 Intent / 自动化 App

## 安全

- 默认 **只读打开**，写入需用户确认
- 白名单动作，禁止任意 shell
