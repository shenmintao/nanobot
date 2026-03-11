# 情感伙伴功能配置指南

完整配置 nanobot 的情感智能对话功能。

## 📋 前置要求

- nanobot 已安装并可运行
- Python 3.10+
- 已有 config.json 配置文件

## 🚀 快速配置（5分钟）

### 步骤 1：配置 SillyTavern

编辑你的 `~/.nanobot/config.json`（或项目配置文件），添加或修改以下部分：

```json
{
  "sillytavern": {
    "enabled": true,
    "response_filter_tag": "speech"
  }
}
```

**说明：**
- `enabled: true` - 启用 SillyTavern 功能
- `response_filter_tag: "speech"` - 从 `<speech>...</speech>` 标签中提取输出内容

### 步骤 2：导入角色卡

```bash
# 进入 nanobot 目录
cd /c/Users/shenmintao/Desktop/nanobot/shenmintao_nanobot

# 导入情感伙伴角色"小爱"
nanobot st char import nanobot/skills/emotional-companion/examples/companion_character.json
```

**验证：**
```bash
# 列出已导入的角色
nanobot st char list
```

你应该看到：
```
小爱 - 一个温暖、善解人意的AI伙伴，总是关注你的情绪和感受
```

### 步骤 3：导入世界设定

```bash
# 导入情感感知世界设定
nanobot st worldinfo import nanobot/skills/emotional-companion/examples/worldinfo_emotional_awareness.json
```

**验证：**
```bash
# 列出世界设定
nanobot st worldinfo list
```

你应该看到：
```
Emotional Awareness - 情感感知
```

### 步骤 4：启用主动关怀（可选）

#### 4.1 启用 Heartbeat 服务

编辑 `~/.nanobot/config.json`：

```json
{
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "interval_s": 3600
    }
  }
}
```

**说明：**
- `enabled: true` - 启用定时任务
- `interval_s: 3600` - 每小时检查一次（可调整）

#### 4.2 创建 HEARTBEAT.md

```bash
# 复制示例文件到 workspace
cp nanobot/skills/emotional-companion/examples/HEARTBEAT.md ~/.nanobot/workspace/HEARTBEAT.md

# 或者如果你有自定义 workspace 路径，替换为你的路径
```

**验证：**
```bash
# 查看文件是否存在
cat ~/.nanobot/workspace/HEARTBEAT.md
```

### 步骤 5：配置渠道（以 WhatsApp 为例）

如果你使用 WhatsApp：

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridge_url": "ws://localhost:3001",
      "allow_from": ["你的手机号"]
    }
  }
}
```

### 步骤 6：完整配置示例

这是一个完整的 `config.json` 示例：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "auto",
      "max_tokens": 8192,
      "temperature": 0.7
    }
  },
  "providers": {
    "anthropic": {
      "api_key": "your-api-key-here"
    }
  },
  "sillytavern": {
    "enabled": true,
    "response_filter_tag": "speech"
  },
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "interval_s": 3600
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridge_url": "ws://localhost:3001",
      "allow_from": []
    }
  }
}
```

### 步骤 7：启动 nanobot

```bash
# 启动 gateway（后台运行）
nanobot gateway start

# 或者前台运行以查看日志
nanobot gateway
```

**查看日志确认：**
```
✓ SillyTavern enabled
✓ Loaded character: 小爱
✓ Loaded world info: Emotional Awareness
✓ Heartbeat started (every 3600s)
```

## 🧪 测试验证

### 测试 1：基础对话

发送消息给 nanobot：
```
你：你好
AI：*微笑着挥手* 嗨！见到你真开心~ 今天过得怎么样？
```

### 测试 2：情感识别

发送消息：
```
你：今天工作好累...
AI：*关切地看着你* 听起来你今天真的很辛苦呢。工作压力大吗？要不要跟我说说发生了什么？
```

### 测试 3：情绪变化

发送消息：
```
你：我考试过了！
AI：*兴奋地拍手* 太棒了！！🎉 我就知道你可以的！一定很有成就感吧？快跟我讲讲~
```

### 测试 4：主动问候（需要等待）

如果配置了 Heartbeat，在设定的时间（如早上8-9点）或长时间未互动后，AI 会主动发送消息：
```
AI：早上好！☀️ 希望你今天一切顺利~
```

## 🔧 高级配置

### 自定义问候时间

编辑 `~/.nanobot/workspace/HEARTBEAT.md`：

```markdown
## 早晨问候 (7-8 AM)
- 发送温暖的早安问候
- 祝愿美好的一天

## 晚间关怀 (21-22 PM)
- 询问今天过得如何
- 提供反思机会
```

### 调整 Heartbeat 频率

更频繁的检查（30分钟）：
```json
{
  "gateway": {
    "heartbeat": {
      "interval_s": 1800
    }
  }
}
```

### 自定义角色人设

你可以编辑角色卡来调整 AI 的性格：

```bash
# 1. 导出当前角色
nanobot st char export 小爱 > my_character.json

# 2. 编辑 my_character.json
# 修改 personality, scenario, mes_example 等字段

# 3. 重新导入
nanobot st char import my_character.json
```

### 添加更多情感触发词

编辑 World Info：

```bash
# 导出
nanobot st worldinfo export "Emotional Awareness - 情感感知" > my_worldinfo.json

# 编辑添加新的 entries
# 例如添加"生气"、"委屈"等新情绪

# 重新导入
nanobot st worldinfo import my_worldinfo.json
```

## 🐛 故障排查

### 问题 1：AI 没有情感回应

**检查清单：**
```bash
# 1. 确认 SillyTavern 已启用
cat ~/.nanobot/config.json | grep -A 3 "sillytavern"

# 2. 确认角色卡已导入
nanobot st char list

# 3. 确认 World Info 已导入
nanobot st worldinfo list

# 4. 查看日志
tail -f ~/.nanobot/logs/gateway.log
```

### 问题 2：没有收到主动问候

**检查清单：**
```bash
# 1. 确认 Heartbeat 已启用
cat ~/.nanobot/config.json | grep -A 3 "heartbeat"

# 2. 确认 HEARTBEAT.md 存在
ls -la ~/.nanobot/workspace/HEARTBEAT.md

# 3. 等待足够时间（至少一个 interval_s）

# 4. 查看 Heartbeat 日志
grep "Heartbeat" ~/.nanobot/logs/gateway.log
```

### 问题 3：回应过于机械

**解决方案：**

1. 增加 temperature（让回应更自然）：
```json
{
  "agents": {
    "defaults": {
      "temperature": 0.8
    }
  }
}
```

2. 丰富角色卡的对话示例：
   - 添加更多 mes_example
   - 增加更多情绪场景

3. 使用更强大的模型：
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-6"
    }
  }
}
```

### 问题 4：角色导入失败

**常见原因：**

1. JSON 格式错误：
```bash
# 验证 JSON 格式
cat nanobot/skills/emotional-companion/examples/companion_character.json | python -m json.tool
```

2. 权限问题：
```bash
# 检查 SillyTavern 数据目录权限
ls -la ~/.nanobot/sillytavern/
```

## 📊 配置验证清单

使用这个清单确保所有配置正确：

- [ ] ✅ SillyTavern 已在 config.json 中启用
- [ ] ✅ 角色卡"小爱"已成功导入
- [ ] ✅ World Info "Emotional Awareness" 已导入
- [ ] ✅ Heartbeat 已启用（如需主动关怀）
- [ ] ✅ HEARTBEAT.md 已放置在 workspace 目录
- [ ] ✅ 渠道（WhatsApp/Telegram 等）已配置
- [ ] ✅ nanobot gateway 已启动
- [ ] ✅ 测试对话显示情感回应

## 🎯 下一步

配置完成后，你可以：

1. **体验对话** - 尝试不同情绪的对话
2. **自定义角色** - 调整 AI 的性格和说话风格
3. **添加记忆** - 使用 memory skill 让 AI 记住重要事件
4. **多渠道使用** - 在 WhatsApp、Telegram 等多个平台使用

## 💡 使用技巧

### 触发情感回应的方法

直接表达情绪：
```
"我好开心！"
"有点难过..."
"压力好大"
```

描述情境：
```
"今天考试没过"
"升职了！"
"和朋友吵架了"
```

### 最佳实践

1. **自然对话** - 像和真人聊天一样自然表达
2. **提供细节** - 更多上下文能得到更贴心的回应
3. **给予反馈** - AI 会从对话中学习调整
4. **定期互动** - 保持连续性有助于建立"关系"

## 📞 获取帮助

如果遇到问题：

1. 查看日志：`~/.nanobot/logs/gateway.log`
2. 检查配置：`nanobot config show`
3. 提交 issue：https://github.com/shenmintao/nanobot/issues

---

**配置完成后，享受有温度的 AI 陪伴！** ❤️
