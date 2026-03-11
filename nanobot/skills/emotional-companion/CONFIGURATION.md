# 情感伙伴配置说明

## 📚 两种配置模式

### 模式 1：标准模式（推荐用于文字聊天）

**特点：** 保留动作描述，对话更生动

**配置：**
```json
{
  "sillytavern": {
    "enabled": true
    // 不设置 response_filter_tag
  }
}
```

**使用角色卡：**
```bash
nanobot st char import nanobot/skills/emotional-companion/examples/companion_character.json
nanobot st worldinfo import nanobot/skills/emotional-companion/examples/worldinfo_emotional_awareness.json
```

**输出效果：**
```
你：今天好累...
AI：*关切地看着你* 听起来你今天真的很辛苦呢。工作压力大吗？
```

**适用场景：**
- ✅ WhatsApp、Telegram 等文字聊天
- ✅ 需要生动表达的场景
- ✅ 角色扮演对话

---

### 模式 2：语音模式（用于 TTS/纯文本）

**特点：** 提取纯对话内容，去除动作描述

**配置：**
```json
{
  "sillytavern": {
    "enabled": true,
    "response_filter_tag": "speech"
  }
}
```

**使用角色卡（重要）：**
```bash
# 使用支持 speech 标签的角色卡
nanobot st char import nanobot/skills/emotional-companion/examples/companion_character_with_speech.json

# 使用语音格式 World Info
nanobot st worldinfo import nanobot/skills/emotional-companion/examples/worldinfo_speech_format.json
```

**输出效果：**
```
你：今天好累...
AI：听起来你今天真的很辛苦呢。工作压力大吗？
```
（动作描述 `*关切地看着你*` 被过滤掉了）

**适用场景：**
- ✅ 语音合成（TTS）
- ✅ 纯文本 API
- ✅ 短信/SMS

---

## 🔍 核心区别

| 对比项 | 标准模式 | 语音模式 |
|-------|---------|---------|
| **配置** | `enabled: true` | `enabled: true`<br/>`response_filter_tag: "speech"` |
| **角色卡** | `companion_character.json` | `companion_character_with_speech.json` |
| **World Info** | `worldinfo_emotional_awareness.json` | `worldinfo_speech_format.json` |
| **输出格式** | `*动作* 对话` | `对话` |
| **是否有动作** | ✅ 有 | ❌ 无 |
| **适合 TTS** | ❌ 不适合 | ✅ 适合 |

---

## ⚙️ 技术细节：`<speech>` 标签如何工作

### 1. 配置侧（系统）

在 `config.json` 中：
```json
{
  "sillytavern": {
    "response_filter_tag": "speech"
  }
}
```

这告诉系统：**从 AI 回复中提取 `<speech>` 标签内的内容**

代码逻辑（在 `nanobot/agent/loop.py`）：
```python
if final_content and self.response_filter:
    final_content = self.response_filter(final_content)
```

### 2. AI 侧（角色）

通过**角色卡的 scenario** 告诉 AI 如何使用标签：

```json
{
  "scenario": "...你实际说的话必须用 <speech> 标签包围..."
}
```

通过**对话示例 mes_example** 展示格式：

```json
{
  "mes_example": "{{char}}: *微笑* <speech>你好！</speech>"
}
```

通过 **World Info** 强化规则：

```json
{
  "content": "{{char}}回复格式：*动作* <speech>对话</speech>"
}
```

### 3. 完整流程

```
1. AI 生成：
   *关切地看着你* <speech>听起来你今天很辛苦呢。</speech>

2. 系统提取 <speech> 标签内容：
   听起来你今天很辛苦呢。

3. 用户收到：
   听起来你今天很辛苦呢。
```

---

## 🚨 常见错误

### 错误 1：设置了 filter 但未用对应角色卡

```json
// config.json
{
  "response_filter_tag": "speech"  // ✓ 设置了
}
```

```bash
# ✗ 错误：使用了不带 speech 的角色卡
nanobot st char import companion_character.json
```

**结果：** AI 不会用 `<speech>` 标签，系统找不到内容，输出为空或出错

**解决：** 使用对应的角色卡
```bash
nanobot st char import companion_character_with_speech.json
```

### 错误 2：未设置 filter 但用了 speech 角色卡

```json
// config.json
{
  "enabled": true
  // ✗ 未设置 response_filter_tag
}
```

```bash
# 使用了带 speech 的角色卡
nanobot st char import companion_character_with_speech.json
```

**结果：** AI 会输出标签，用户看到 `<speech>...</speech>`

**解决：** 添加配置或换回标准角色卡

---

## ✅ 配置验证清单

### 标准模式清单

- [ ] `sillytavern.enabled: true`
- [ ] **未设置** `response_filter_tag`
- [ ] 导入 `companion_character.json`
- [ ] 导入 `worldinfo_emotional_awareness.json`
- [ ] 测试输出包含动作描述

### 语音模式清单

- [ ] `sillytavern.enabled: true`
- [ ] `response_filter_tag: "speech"`
- [ ] 导入 `companion_character_with_speech.json`
- [ ] 导入 `worldinfo_speech_format.json`
- [ ] 测试输出为纯文本（无动作）

---

## 🔄 切换模式

### 从标准模式 → 语音模式

```bash
# 1. 修改 config.json，添加 response_filter_tag
# 2. 移除旧角色
nanobot st char delete 小爱

# 3. 导入新角色
nanobot st char import companion_character_with_speech.json
nanobot st worldinfo import worldinfo_speech_format.json

# 4. 重启 nanobot
nanobot gateway restart
```

### 从语音模式 → 标准模式

```bash
# 1. 修改 config.json，移除 response_filter_tag
# 2. 移除旧角色
nanobot st char delete "小爱（语音优化版）"

# 3. 导入标准角色
nanobot st char import companion_character.json
nanobot st worldinfo import worldinfo_emotional_awareness.json

# 4. 重启 nanobot
nanobot gateway restart
```

---

## 💡 推荐配置

### 对于 95% 的用户

使用**标准模式**（不设置 `response_filter_tag`）

**理由：**
- 对话更生动有趣
- 情感表达更丰富
- 符合 SillyTavern 设计理念

### 仅在以下情况使用语音模式

- ✅ 需要 TTS 语音输出
- ✅ 集成到仅支持纯文本的第三方应用
- ✅ 短信/SMS 等简洁渠道

---

## 📞 获取帮助

遇到问题？

1. 检查配置是否匹配（模式 vs 角色卡）
2. 查看日志：`tail -f ~/.nanobot/logs/gateway.log`
3. 测试 AI 输出是否包含 `<speech>` 标签
4. 提交 issue 并附上配置和输出示例
