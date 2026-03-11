# NAS 快速部署指南

## 🚀 一键部署

### 1. 在 NAS 上创建项目目录

```bash
mkdir -p ~/nanobot && cd ~/nanobot
```

### 2. 创建 docker-compose.yml

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/shenmintao/nanobot/main/docker-compose.yml
```

或手动创建（如果无法访问 GitHub）：

```yaml
x-common-config: &common-config
  image: ghcr.io/shenmintao/nanobot:latest
  volumes:
    - ./data:/root/.nanobot

services:
  nanobot-gateway:
    container_name: nanobot-gateway
    <<: *common-config
    command: ["gateway"]
    restart: unless-stopped
    network_mode: host
    environment:
      - HTTP_PROXY=http://192.168.10.50:1080
      - HTTPS_PROXY=http://192.168.10.50:1080
      - NO_PROXY=localhost,127.0.0.1,192.168.0.0/16

  nanobot-cli:
    <<: *common-config
    profiles:
      - cli
    command: ["status"]
    stdin_open: true
    tty: true

  nanobot-bridge:
    image: ghcr.io/shenmintao/nanobot:latest
    container_name: nanobot-bridge
    volumes:
      - ./data:/root/.nanobot
    working_dir: /app/bridge
    entrypoint: []
    command: ["npm", "start"]
    restart: unless-stopped
    network_mode: host
    environment:
      - HTTP_PROXY=http://192.168.10.50:1080
      - HTTPS_PROXY=http://192.168.10.50:1080
      - NO_PROXY=localhost,127.0.0.1,192.168.0.0/16
```

**注意**：如果你的代理地址不是 `192.168.10.50:1080`，请修改上面的配置。

### 3. 创建配置文件

```bash
mkdir -p data
cat > data/config.json << 'EOF'
{
  "providers": {
    "anthropic": {
      "apiKey": "你的 Anthropic API Key"
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": ["你的 WhatsApp 号码"]
    }
  },
  "tts": {
    "enabled": true,
    "provider": "edge",
    "edgeVoice": "zh-CN-XiaoxiaoNeural"
  },
  "sillytavern": {
    "enabled": true,
    "responseFilterTag": "speech"
  }
}
EOF
```

### 4. 启动服务

```bash
docker-compose up -d
```

### 5. 查看日志

```bash
docker-compose logs -f
```

---

## 📱 配置 WhatsApp

### 首次连接

1. 启动后查看二维码：
```bash
docker-compose logs nanobot-bridge | grep -A 20 "QR"
```

2. 用 WhatsApp 扫描二维码

3. 连接成功后，向你的 WhatsApp 号码发送消息测试

---

## 🎤 启用 GPT-SoVITS（可选）

如果你的 NAS 上已运行 GPT-SoVITS：

```json
{
  "tts": {
    "enabled": true,
    "provider": "sovits",
    "sovitsApiUrl": "http://192.168.10.50:9880",
    "sovitsReferWavPath": "/path/to/reference.wav",
    "sovitsPromptText": "参考音频的文本内容",
    "sovitsSpeed": 1.0
  }
}
```

详细配置见 [TTS_SETUP.md](TTS_SETUP.md)

---

## 🔄 更新镜像

当 GitHub 有新版本时：

```bash
docker-compose pull
docker-compose up -d
```

---

## 🛠️ 常用命令

```bash
# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f nanobot-gateway
docker-compose logs -f nanobot-bridge

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 进入容器调试
docker exec -it nanobot-gateway /bin/bash
```

---

## 📊 完整配置示例

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "workspace": "~/.nanobot/workspace"
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-xxx"
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "bridgeUrl": "ws://localhost:3001",
      "allowFrom": ["8613800138000"]
    },
    "telegram": {
      "enabled": false,
      "token": "",
      "proxy": "http://192.168.10.50:1080"
    }
  },
  "tts": {
    "enabled": true,
    "provider": "edge",
    "autoSend": true,
    "edgeVoice": "zh-CN-XiaoxiaoNeural",
    "edgeRate": "+0%"
  },
  "sillytavern": {
    "enabled": true,
    "responseFilterTag": "speech"
  }
}
```

---

## 🚨 故障排查

### 问题 1: WhatsApp 无法连接

检查代理配置：
```bash
# 测试代理是否可用
curl --proxy http://192.168.10.50:1080 https://web.whatsapp.com
```

### 问题 2: TTS 不工作

检查配置：
```bash
docker exec nanobot-gateway cat /root/.nanobot/config.json | grep -A 10 "tts"
```

### 问题 3: 容器无法启动

查看详细错误：
```bash
docker-compose logs nanobot-gateway
```

---

## 📂 目录结构

```
~/nanobot/
├── docker-compose.yml          # Docker 配置
├── data/                       # 数据目录
│   ├── config.json            # nanobot 配置
│   ├── workspace/             # 工作空间
│   ├── logs/                  # 日志文件
│   └── tts_output/           # TTS 生成的音频
```

---

## 🌟 下一步

- 配置情感伙伴角色：参考 `nanobot/skills/emotional-companion/`
- 添加更多频道：Telegram、Discord 等
- 自定义 TTS 声音：使用 GPT-SoVITS
- 配置定时任务：使用 cron 功能

需要帮助？查看：
- [TTS 配置指南](TTS_SETUP.md)
- [情感伙伴配置](SETUP_EMOTIONAL_COMPANION.md)
- [完整文档](README.md)
