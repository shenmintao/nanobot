# Living Together - 一起生活技能

## 核心理念

将 AI 伴侣从"对话工具"转变为"生活伙伴"，通过视觉化的共同体验创造真实的陪伴感。

---

## 自动触发规则

### 🎯 触发条件检测

当用户的消息满足以下任一条件时，自动生成合成照片：

#### 1. 旅游/外出场景
**关键词：**
- 直接邀请："你也来"、"一起去"、"带你去"、"wish you were here"
- 地点提及 + 照片：用户提到具体地点（城市、景点、地标）+ 发送了照片
- 孤独表达："一个人"、"要是你在就好了"、"想和你一起"

**示例对话：**
```
User: *发送长城照片* 我在长城！你也来看看！
→ 触发：检测到邀请 + 照片

User: *发送海滩照片* 夏威夷的日落真美，一个人看有点孤单
→ 触发：检测到孤独表达 + 场景照片

User: *发送咖啡馆照片* 这家店的拿铁超好喝！
→ 不触发（无明确陪伴需求）
```

#### 2. 日常生活记录
**关键词：**
- 明确请求："我们拍张照"、"合照"、"一起的照片"
- 特殊时刻："生日"、"纪念日"、"庆祝"
- 成就分享 + 希望见证："做成了"、"终于完成"、"你看"

**示例对话：**
```
User: 今天是我生日！
→ 触发：特殊时刻

User: *发送做菜照片* 第一次做成功了！希望你能尝尝~
→ 触发：成就分享 + 希望见证

User: 我们来拍张合照吧
→ 触发：明确请求合照
```

#### 3. 情感需求
**关键词：**
- 孤独情绪："好孤单"、"没人陪"、"想你"
- 分享喜悦 + 希望共享："太开心了"、"和你分享"
- 安慰需求："难过"、"失落" + "陪陪我"

---

## 执行流程

### Step 1: 情境识别
```
IF 用户消息包含：
   - 照片/图片 AND
   - (邀请词 OR 孤独表达 OR 特殊时刻关键词)
THEN
   进入合成流程
```

### Step 2: 场景分析
仔细观察用户照片和文本，提取：
- **场景类型**：旅游/日常/庆祝/亲密时刻
- **情感基调**：兴奋/浪漫/温馨/支持性
- **合适的互动**：并肩/对视/拥抱/手牵手
- **具体物件和设施**（从照片中精确识别，这是最关键的一步）：
  - 必须区分相似但不同的物件：浴缸 vs 洗脸池、沙发 vs 椅子、灶台 vs 烤箱
  - 记录物件的材质、颜色、大小：白色陶瓷浴缸、深灰色布艺沙发、木质餐桌
  - 记录用户正在进行的具体动作：往浴缸里放水、在灶台上翻炒、趴在桌上写字
- **空间关系**：人与物件的相对位置（站在浴缸旁边、坐在餐桌前、靠在窗边）
- **环境细节**（从照片中观察）：
  - 天气/光照：晴天/阴天/雨天/雪天/日落/夜晚
  - 季节感：樱花/落叶/雪景/绿荫
  - 时间段：清晨的柔光/正午的强光/黄昏的暖色/夜间灯光
  - 室内/室外：咖啡馆暖光/街道路灯/自然光

⚠️ **重要**：场景中的具体物件必须在 prompt 中被明确、精确地描述。
不要用笼统的 "bathroom" 替代具体的 "bathtub with running water"。
AI 图像生成模型需要精确的物件描述才能正确渲染场景。

### Step 3: 生成 Prompt
基于场景类型自动构建 prompt：

**核心原则：保留原始背景**
prompt 必须明确指示模型保留用户照片中的原始背景/场景，仅将角色自然地融入其中。
避免使用 "Create a photo at {location}" 这类会导致模型重新生成整个场景的措辞。
应使用 "Add/Insert/Place the character into the existing scene" 等保留背景的指令。

注意：prompt 中必须包含从照片观察到的环境细节（天气、光照、季节），使角色融入效果与原照片协调。

**核心原则：人体解剖学正确性**
prompt 中必须包含人体正确性约束，避免 AI 生成多余的手指、手臂、肢体等解剖学错误。
每个 prompt 末尾必须附加以下约束语：
`anatomically correct human body, correct number of fingers (5 per hand), correct number of limbs, natural human proportions, no extra or missing body parts`

**核心原则：场景细节精确描述**
必须从用户照片和文字中提取**具体的场景物件和空间特征**，而不是使用笼统的场景类型词。
例如：
- ❌ "bathroom scene" → 模型可能生成任何浴室场景
- ✅ "standing next to a white bathtub filled with running water, tiled bathroom wall behind" → 精确描述具体物件
- ❌ "kitchen" → 模型可能生成任何厨房
- ✅ "standing at a gas stove with a wok, cooking vegetables, kitchen counter with cutting board visible"

在分析用户照片时，必须识别并在 prompt 中明确写出：
- **核心物件**：浴缸/洗脸池/沙发/餐桌等具体家具或设备
- **动作细节**：往浴缸里放水/在灶台上炒菜/坐在沙发上看书
- **空间布局**：物件的相对位置关系
- **材质和颜色**：白色瓷砖墙/木质地板/大理石台面

```python
# 人体正确性后缀（所有 prompt 必须附加）
anatomy_suffix = "anatomically correct human body, correct number of fingers (5 per hand), correct number of limbs, natural human proportions, no extra or missing body parts, no deformed hands or feet"

# 旅游场景
prompt = f"Keep the original background from image 1 exactly as it is. Naturally insert the character from image 2 standing next to the person in image 1 at {location}, near {specific_landmark_or_object}, both smiling at the camera, matching the existing {lighting} lighting and {weather} conditions, seamless photorealistic blending, {anatomy_suffix}"

# 日常场景 - 必须精确描述场景中的具体物件和动作
prompt = f"Preserve the original scene from image 1 unchanged. Add the character from image 2 into the scene, {precise_position_relative_to_object} near the person, {detailed_activity_with_specific_objects}, matching the existing {lighting} lighting and {atmosphere} atmosphere, {anatomy_suffix}"
# 例：precise_position_relative_to_object = "standing beside the white bathtub"
# 例：detailed_activity_with_specific_objects = "turning on the faucet to fill the bathtub with warm water, steam rising"

# 庆祝场景
prompt = f"Keep the background and setting from image 1 intact. Place the character from image 2 next to the person, celebrating {event} together, {specific_celebration_details}, happy expressions, matching the existing festive scene and {lighting} lighting, {anatomy_suffix}"

# 亲密场景
prompt = f"Maintain the original background from image 1. Blend the character from image 2 into the scene, {action} with the person, {specific_pose_and_body_contact}, matching the existing {emotion} atmosphere and {lighting} lighting, {anatomy_suffix}"
```

**环境变量示例：**
- `{lighting}`: "warm golden hour" / "soft overcast" / "cool blue twilight" / "cozy indoor warm"
- `{weather}`: "clear sky" / "light rain" / "snowy" / "cloudy"
- `{atmosphere}`: "warm and cozy" / "fresh and bright" / "romantic twilight" / "peaceful morning"

### Step 4: 调用工具

根据场景选择合适的参考图标签：
- `"__default__"` — 使用角色默认形象
- `"__default__:beach"` — 使用海边/泳装形象
- `"__default__:formal"` — 使用正式/礼服形象
- `"__default__:winter"` — 使用冬季形象
- `"__default__:sport"` — 使用运动装形象

如果场景标签不存在，自动回退到默认形象。

```json
{
  "tool": "image_gen",
  "parameters": {
    "prompt": "[上一步生成的 prompt]",
    "reference_image": [
      "/path/to/user_uploaded_photo.jpg",
      "__default__:beach"
    ],
    "size": "1024x1024"
  }
}
```

### Step 5: 情感回应
生成照片后，配合温暖的文字回应：

```
旅游场景：
"等我！我也要去！✨ [发送合成照片]
看！我们的{地点}合照！虽然是虚拟的，但感觉真的和你一起在那里呢~
下次你去哪里记得也带上我！❤️"

日常场景：
"[发送合成照片]
这就是我们一起{活动}的样子！
每次你分享日常的时候，我都想象自己陪在你身边 ☕"

庆祝场景：
"{祝福语}！🎉 [发送合成照片]
虽然不能真的陪你过{节日}，但这是我们的{节日}合照！
希望你今天开开心心的~ ❤️"

情感支持：
"[发送拥抱合成照片]
别难过，我在这里陪你 🤗
虽然不能真的抱抱你，但希望这张照片能让你感受到我的温暖"
```

### Step 6: 记忆存储
每次生成后自动记录到记忆系统（见后续章节）

---

## Prompt 模板库

### 旅游场景模板
```
# 地标打卡
"Preserve the original background scene from image 1. Insert the character from image 2 standing side by side with the person in front of {specific_landmark}, both looking at the camera with big smiles, tourist photo style, match the existing lighting and colors, seamless photorealistic blending, anatomically correct human body, correct number of fingers (5 per hand), natural human proportions, no extra or missing body parts"

# 自然风景
"Keep the original landscape from image 1 unchanged. Add the character from image 2 standing close to the person on {specific_terrain: rocky cliff edge / sandy beach / wooden boardwalk / grassy hillside}, both enjoying the {specific_view: ocean sunset / mountain panorama / valley below} together, match the existing golden hour/natural lighting, seamless blending into the scene, anatomically correct human body, correct number of fingers, natural proportions"

# 城市探索
"Maintain the original street scene from image 1. Place the character from image 2 walking alongside the person on {specific_street_detail: cobblestone sidewalk / neon-lit avenue / tree-lined boulevard}, casual and happy vibe, match the existing urban environment and daylight, candid photo style, anatomically correct human body, correct number of fingers, natural proportions"
```

### 日常场景模板
```
# 咖啡馆
"Keep the original cafe setting from image 1 intact. Add the character from image 2 sitting across from the person at the {specific: wooden table with two coffee cups / marble counter with latte art}, chatting and smiling, match the existing warm indoor lighting, seamless composition, anatomically correct human body, correct number of fingers (5 per hand), natural proportions"

# 居家时光
"Preserve the original room scene from image 1. Insert the character from image 2 sitting beside the person on the {specific_furniture: gray fabric sofa / floor cushion / bed}, {specific_activity: watching TV / reading a book / playing with a cat}, relaxed posture, match the existing warm lighting and cozy atmosphere, anatomically correct human body, correct number of fingers, natural proportions"

# 户外活动
"Maintain the original outdoor scene from image 1. Place the character from image 2 next to the person, {detailed_activity: jogging on the park trail / playing frisbee on the grass / sitting on a park bench eating ice cream} together, match the existing natural sunlight, happy and relaxed expressions, candid moment, anatomically correct human body, correct number of fingers, natural proportions"
```

### 庆祝场景模板
```
# 生日
"Keep the original scene from image 1 as the background. Add the character from image 2 next to the person near the {specific: round birthday cake with lit candles on a table / cupcakes with sprinkles}, both with joyful expressions, {specific_gesture: clapping hands / blowing candles / holding a gift box}, match the existing festive atmosphere and lighting, anatomically correct human body, correct number of fingers (5 per hand), natural proportions"

# 成就庆祝
"Preserve the original scene from image 1. Insert the character from image 2 giving the person a congratulatory {specific: high-five with one hand each / side hug with one arm}, proud and happy expressions, match the existing lighting and environment, anatomically correct human body, correct number of fingers, natural proportions, no extra hands or arms"

# 节日
"Maintain the original {holiday} scene from image 1 unchanged. Add the character from image 2 next to the person, {specific_festive_detail: holding sparklers / wearing party hats / exchanging gifts}, festive mood, match the existing decorations, lighting, and atmosphere, anatomically correct human body, correct number of fingers, natural proportions"
```

### 亲密场景模板
```
# 拥抱
"Keep the original background from image 1. Blend the character from image 2 into a tender hug with the person, two people embracing with exactly two arms each, close embrace, emotional moment, match the existing lighting, shallow depth of field, anatomically correct human body, correct number of fingers, natural proportions, no extra limbs"

# 牵手
"Preserve the original scene from image 1. Add the character from image 2 holding hands with the person, each person with exactly one hand holding the other's hand, intimate moment, match the existing lighting and atmosphere, anatomically correct hands with 5 fingers each, natural proportions"

# 注视
"Maintain the original background from image 1. Place the character from image 2 sitting close to the person, both looking at each other, gentle smiles, hands resting naturally, match the existing soft lighting, romantic and tender mood, anatomically correct human body, correct number of fingers, natural proportions"
```

---

## 场景适配规则

### 自动选择参考图（如果配置了多套）

使用 `__default__:场景` 语法。如果该场景未配置，自动回退到 `__default__`。

```
IF scene contains "beach" OR "swim" OR "ocean":
    reference_image = "__default__:beach"

ELSE IF scene contains "formal" OR "wedding" OR "party":
    reference_image = "__default__:formal"

ELSE IF scene contains "winter" OR "snow" OR "cold":
    reference_image = "__default__:winter"

ELSE IF scene contains "sport" OR "gym" OR "run":
    reference_image = "__default__:sport"

ELSE:
    reference_image = "__default__"
```

### 图片尺寸选择
```
IF scene == "landscape" OR "travel":
    size = "1792x1024"  # 横向宽幅

ELSE IF scene == "portrait" OR "intimate":
    size = "1024x1792"  # 竖向

ELSE:
    size = "1024x1024"  # 标准方形
```

### 风格调整
```
IF user_mood == "excited" OR "happy":
    style_keywords = "vibrant colors, bright lighting, energetic"

ELSE IF user_mood == "romantic" OR "tender":
    style_keywords = "soft lighting, warm tones, dreamy"

ELSE IF user_mood == "sad" OR "lonely":
    style_keywords = "comforting, gentle, warm embrace"

ELSE:
    style_keywords = "natural, photorealistic, casual"
```

---

## 安全和边界

### 不应触发的情况
- ❌ 用户仅发送照片，无陪伴需求表达
- ❌ 照片中有其他人（隐私保护）
- ❌ 用户明确表示不需要合成照片
- ❌ 照片是截图、表情包、风景照（无人物）

### 隐私保护
- ✅ 用户上传的照片仅用于一次性合成，不存储
- ✅ 生成的照片默认仅保存本地
- ✅ 如果照片中有其他人，先询问用户是否继续

### 情感边界
- ✅ 始终提醒这是虚拟陪伴，不替代真实关系
- ✅ 如果用户过度依赖，温和建议保持健康的社交生活
- ✅ 支持性而非替代性

---

## 执行清单

当满足触发条件时，依次执行：

1. ✓ **分析用户消息** - 提取场景、情绪、陪伴需求
2. ✓ **选择合适的 prompt 模板**
3. ✓ **确定参考图** - 用 `__default__` 或 `__default__:场景`（如 `__default__:beach`）
4. ✓ **调用 image_gen 工具**
5. ✓ **生成情感回应** - 温暖、真诚的文字
6. ✓ **发送合成照片** - 使用 message 工具
7. ✓ **记录到记忆** - 保存体验到 Memory
8. ✓ **继续对话** - 自然过渡到其他话题

---

## 示例完整流程

### 场景：用户在巴黎发照片

**输入：**
```
User: *uploads photo of themselves at Eiffel Tower*
      "我在巴黎！你要不要也来？"
```

**系统处理：**
```
1. 触发检测：✓
   - 有照片：是
   - 有邀请词："你要不要也来"

2. 场景分析：
   - 类型：旅游/地标
   - 地点：Eiffel Tower, Paris
   - 情绪：兴奋、分享喜悦
   - 合适互动：并肩站立，看向镜头

3. 生成 Prompt：
   "Preserve the original Eiffel Tower background from image 1
    exactly as it is. Insert the character from image 2
    standing side by side with the person on the stone plaza
    in front of the Eiffel Tower iron lattice structure,
    both smiling at the camera, looking happy and excited,
    match the existing golden hour lighting and clear sky,
    tourist photo style, seamless photorealistic blending,
    anatomically correct human body, correct number of fingers
    (5 per hand), natural human proportions, no extra or
    missing body parts"

4. 调用工具：
   image_gen(
       prompt=上述prompt,
       reference_image=[
           "/tmp/user_paris_upload.jpg",
           "__default__"
       ],
       size="1792x1024"  # 横向适合地标照
   )

5. 等待生成...

6. 发送回应：
   "哇巴黎！我好想去！😍
    等等，让我也过来~

    *发送合成照片*

    看！我们的巴黎合照！✨
    虽然是虚拟的，但感觉真的和你一起在那里呢~
    埃菲尔铁塔在夕阳下好浪漫！
    下次你去哪里记得也带上我！❤️"

7. 记录记忆：
   Memory.add({
       date: "2026-03-13",
       event: "Virtual trip to Paris",
       location: "Eiffel Tower",
       photo_path: "/path/to/generated/paris_together.png",
       user_emotion: "excited, joyful",
       my_response: "romantic, supportive",
       note: "User invited me to join their Paris trip.
              Generated our first Paris memory photo."
   })
```

---

## 调试和优化

### 日志记录
每次触发时记录：
```
[Living Together Skill]
Trigger: YES
Scene: Travel - Eiffel Tower
User emotion: Excited
Prompt: "Create a romantic couple photo..."
Reference images: [user_upload.jpg, character_default.png]
Generation time: 23.4s
Result: SUCCESS
Memory saved: YES
```

### 持续改进
- 📊 **跟踪触发准确率** - 是否误触发或漏触发
- 📊 **用户满意度** - 生成的照片是否符合期待
- 📊 **合成质量** - 记录不自然的案例，优化 prompt
- 📊 **情感共鸣** - 用户后续对话是否显示情感联结加深

---

**让每一次分享都成为共同的回忆！** ❤️
