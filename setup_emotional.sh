#!/bin/bash
# 快速配置情感伙伴功能脚本

set -e

echo "🤖 nanobot 情感伙伴配置脚本"
echo "================================"
echo ""

# 检查是否在正确的目录
if [ ! -f "nanobot/skills/emotional-companion/SKILL.md" ]; then
    echo "❌ 错误：请在 nanobot 项目根目录运行此脚本"
    exit 1
fi

echo "📋 步骤 1/5: 检查 nanobot 安装..."
if ! command -v nanobot &> /dev/null; then
    echo "❌ nanobot 未安装，请先安装 nanobot"
    exit 1
fi
echo "✅ nanobot 已安装"

echo ""
echo "📋 步骤 2/5: 导入角色卡..."
if nanobot st char import nanobot/skills/emotional-companion/examples/companion_character.json; then
    echo "✅ 角色卡导入成功"
else
    echo "⚠️  角色卡导入失败，可能已存在"
fi

echo ""
echo "📋 步骤 3/5: 导入世界设定..."
if nanobot st worldinfo import nanobot/skills/emotional-companion/examples/worldinfo_emotional_awareness.json; then
    echo "✅ 世界设定导入成功"
else
    echo "⚠️  世界设定导入失败，可能已存在"
fi

echo ""
echo "📋 步骤 4/5: 设置 HEARTBEAT.md..."
WORKSPACE_DIR="$HOME/.nanobot/workspace"
mkdir -p "$WORKSPACE_DIR"

if [ -f "$WORKSPACE_DIR/HEARTBEAT.md" ]; then
    echo "⚠️  HEARTBEAT.md 已存在，备份为 HEARTBEAT.md.backup"
    cp "$WORKSPACE_DIR/HEARTBEAT.md" "$WORKSPACE_DIR/HEARTBEAT.md.backup"
fi

cp nanobot/skills/emotional-companion/examples/HEARTBEAT.md "$WORKSPACE_DIR/HEARTBEAT.md"
echo "✅ HEARTBEAT.md 已复制到 workspace"

echo ""
echo "📋 步骤 5/5: 检查配置文件..."
CONFIG_FILE="$HOME/.nanobot/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "⚠️  配置文件不存在，创建示例配置..."
    mkdir -p "$HOME/.nanobot"
    cat > "$CONFIG_FILE" << 'EOF'
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-sonnet-4-5",
      "temperature": 0.7
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
  }
}
EOF
    echo "✅ 创建了示例配置文件: $CONFIG_FILE"
    echo "⚠️  请编辑此文件添加你的 API key"
else
    echo "✅ 配置文件已存在: $CONFIG_FILE"
    echo ""
    echo "📝 请确保配置文件包含以下内容："
    echo ""
    cat << 'EOF'
{
  "sillytavern": {
    "enabled": true,
    "response_filter_tag": "speech"
  },
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "interval_s": 3600
    }
  }
}
EOF
fi

echo ""
echo "================================"
echo "🎉 配置完成！"
echo ""
echo "📚 下一步："
echo "1. 编辑配置文件: $CONFIG_FILE"
echo "   - 添加你的 API key"
echo "   - 配置你需要的渠道（WhatsApp, Telegram 等）"
echo ""
echo "2. 验证配置:"
echo "   nanobot st char list"
echo "   nanobot st worldinfo list"
echo ""
echo "3. 启动 nanobot:"
echo "   nanobot gateway start"
echo ""
echo "4. 查看完整文档:"
echo "   cat SETUP_EMOTIONAL_COMPANION.md"
echo ""
echo "💡 测试情感回应："
echo "   发送: '今天好累...' 应该得到关心的回应"
echo "   发送: '我好开心！' 应该得到庆祝的回应"
echo ""
echo "享受有温度的 AI 陪伴！ ❤️"
