# 专用人设模型与情感 TTS 路线图

## 你现在有的三层能力

| 层 | 实现 | 文件 |
|---|---|---|
| 固定人设 | 人设圣经（不可漂移） | `config/persona_luoyao.yaml` |
| 固定人设 | 人设圣经 + 音色锚点（两段原台词）常驻 system prompt | `companion_persona.py` + `persona_luoyao.yaml` |
| 长期记忆 | 事实 / 开放情绪 / 约定 / 关系备注 / 会话摘要 | `companion_memory.py` |
| 微调数据 | 仅导出训练用，**不参与对话检索** | `data/dialogue_examples.jsonl` |
| 情绪播报 | LLM 输出 `<<emotion:...>>` → TTS 语速音高 + 多句分段 | `voice_io.text_to_speech_performative` |

这 **不是真微调**，但用「固定人设 + 范例 RAG」在工程上接近 **专用人设模型的 MVP**。

---

## 路径 A：继续堆范例（零训练，最快）

1. 在 `data/dialogue_examples.jsonl` 追加你喜欢的路遥台词（一行一条 JSON）
2. 格式：

```json
{"scene":"tired","user":"用户原话","assistant":"路遥回复","emotion":"soft"}
```

3. 用 `python3 src/companion_chat.py` 快速试，满意再跑语音

**目标**：范例库 80–150 条，覆盖你最常见的 15 个场景。

---

## 路径 B：导出微调数据集（真·专用人设模型）

```bash
cd companion-robot
python3 scripts/export_finetune_dataset.py
```

生成 `data/finetune_luoyao.jsonl`，每行一条 OpenAI 格式多轮或单轮对话。

### 推荐微调底座

| 模型 | 体量 | 适合 |
|---|---|---|
| Qwen2.5-7B-Instruct | 7B | Mac / 单卡 GPU LoRA |
| Qwen2.5-14B-Instruct | 14B | 更好人设，需更大显存 |
| DeepSeek 官方微调 | 视平台 | 若开放 character fine-tune |

### LoRA 工具链（示例）

- **LLaMA-Factory** / **ms-swift** / **Unsloth**
- 数据：`finetune_luoyao.jsonl`
- 训练目标：assistant 回复风格固定为路遥，system 可简化

微调后部署：

- 树莓派：7B 全量推理吃力，建议 **Mac/服务器跑模型**，Pi 只负责麦和喇叭
- 改 `src/.env`：`DEEPSEEK_BASE_URL` 指向本地 OpenAI 兼容接口（如 vLLM / Ollama）

---

## 路径 C：情感 TTS 升级（表演感）

### 当前（已实现）

- edge-tts 云希 + 情绪映射（soft/happy/silence/sad/presence）
- 多句回复：后半段更慢更轻（`performative_tts: true`）

### 下一阶段选项

| 方案 | 情感表现 | 树莓派 5 |
|---|---|---|
| 火山引擎 / 阿里云情感 TTS | 强 | 需 API Key，Pi 联网调用 |
| CosyVoice / ChatTTS | 很强 | 建议 Mac 起服务，Pi 调 HTTP |
| GPT-SoVITS 声音克隆 | 可克隆路遥向男声 | Mac 训练 + 推理 |

在 `voice_io.py` 增加 `tts_backend: cosyvoice` 时，Pi 请求 `http://你的Mac:端口/synthesize?emotion=soft`。

---

## 记忆文件结构（v2）

`data/companion_memory.json` 现包含：

- `facts` — 长期事实
- `open_loops` — 未完成情绪（可回访）
- `promises` — 约定
- `relationship_notes` — 相处偏好
- `session_summaries` — 每 8 轮自动摘要
- `turn_count` — 对话轮次

可在 App 里做「记忆页」让用户删改——当前为本地 JSON。

---

## 推荐落地顺序

1. **本周**：你补 20 条最满意的路遥台词进 `dialogue_examples.jsonl`
2. **下周**：Mac 上试 Qwen2.5-7B LoRA（用导出数据集）
3. **并行**：试火山/ CosyVoice 情感 TTS 替换 edge-tts

有抖音路遥原话可贴给我，我直接帮你灌进范例库。
