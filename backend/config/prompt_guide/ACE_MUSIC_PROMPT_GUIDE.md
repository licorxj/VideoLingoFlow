# ACE-Step 提示词（Prompt）撰写指南与示例

> 适用版本：ACE-Step v1.5   
> 配套示例json：本文档同名目录下的example_**.json

本文说明如何撰写高质量的音乐生成提示词，涵盖**音乐描述（caption/prompt）**与**歌词（lyrics）**的写法、可用的结构标签、典型示例，以及**纯音乐（instrumental）**写法。

---

## 一、提示词的两大组成部分

| 部分 | 含义 | 字段 / 标签 | 说明 |
|------|------|-------------|------|
| **音乐描述** | 用自然语言描述曲风、乐器、情绪、人声 | 本地 `prompt` / `caption`；云端 `<prompt>` 标签 | 决定「这首歌听起来是什么样的」 |
| **歌词** | 带结构标记的词 | 本地 `lyrics`；云端 `<lyrics>` 标签 | 决定「唱什么、段落如何排布」 |

两者可以只给其一，也可以都给；都给时控制力最强。

---

## 二、音乐描述（caption）撰写规则

### 2.1 推荐包含 4 个要素
1. **风格 / 流派**（genre）：pop、rock、jazz、lo-fi hip hop、orchestral、EDM、trap、anime theme…
2. **乐器 / 编排**（instruments）：acoustic guitar、synth pad、808 sub-bass、drum machine、strings、piano…
3. **情绪 / 氛围**（mood）：gentle、melancholic、energetic、epic、dreamy、warm…
4. **人声类型**（vocal，可选）：male/female vocal、clear vocal、rap、choir…

### 2.2 可选元数据（直接在描述里写，或用独立字段）
| 项 | 写法示例 | 备注 |
|----|----------|------|
| BPM | `80 BPM` / `mid-tempo` | 不写由模型自定 |
| 调式 | `C major` / `B minor` / `E♭ minor` | 即 `keyscale` |
| 拍号 | `4/4` | 合法值：2、3、4、6 |
| 语言 | `女声（中文）` / `French rap` | 也可用 `vocal_language` 字段，见 §5 |

### 2.3 好的 vs 差的对比
- ❌ 差：`一首好听的歌`（太笼统，模型只能随机发挥）
- ✅ 好：`A gentle acoustic ballad with female vocals, 80 BPM, warm and intimate, soft nylon guitar and light brushed drums`
- ✅ 好（中文）：`C 大调温柔的原声情歌，80 BPM，女声，尼龙弦吉他与轻盈的鼓刷`

> 提示：开启 `use_format` / `use_cot_caption` 后，云端 LLM 会对你的描述做**润色与结构补全**（即“LM 提示词优化”），描述写简单些也没关系。

---

## 三、歌词（lyrics）撰写规则

### 3.1 结构标签（段落标记）
用方括号 `[ ]` 标注段落，模型据此组织歌曲结构。项目样例中出现过、模型可识别的标签包括：

| 标签 | 含义 |
|------|------|
| `[Intro]` | 前奏（纯乐器引入） |
| `[Verse 1]` / `[Verse 2]` … | 主歌 |
| `[Pre-Chorus]` | 预副歌 |
| `[Chorus]` | 副歌（高潮） |
| `[Bridge]` | 桥段 |
| `[Outro]` | 尾奏 |
| `[Instrumental Break]` / `[Instrumental]` | 乐器间奏 |
| `[inst]` | 整首纯器乐占位（见 §4） |
| `[Song ends abruptly]` | 戛然而止收尾（风格化标记） |

### 3.2 标签用法要点
- **段落之间用空行分隔**，便于模型切分。
- **副歌（Chorus）重复出现**时，歌词可重复写，也可只写一次由模型复用。
- 结构越清晰，成歌结构越贴近预期；纯一段词不标标签也能生成，但段落感较弱。

### 3.3 歌词示例片段
```text
[Verse 1]
黑夜里的风吹过耳畔
甜蜜时光转瞬即万

[Chorus]
心电感应在震动间
拥抱未来勇敢冒险
那旋律在心中无限
世界变得如此耀眼

[Bridge]
光影交错彼此的视线
月光洒下温热心田

[Outro]
（渐弱收尾）
```

---

## 四、纯音乐（Instrumental）写法

纯音乐 = 没有人声。核心是：**歌词要么不写，要么只写 `[inst]`**；描述里点明“无人声 / 配乐”即可。

### 写法 A：描述里说明“无人声”，歌词写 `[inst]`
- 音乐描述：`<prompt>Dreamy lo-fi hip hop beat with vinyl crackle</prompt>`
- 歌词：`<lyrics>[inst]</lyrics>`

### 写法 B：开启 instrumental 开关（在请求里设 `instrumental: true`），不写歌词
- 音乐描述：`<prompt>史诗感管弦乐配乐，恢弘有力</prompt>`

### 写法 C：只给描述，强调无 vocal
- 音乐描述：`epic orchestral soundtrack, no vocals, sweeping strings and brass, triumphant`

> 纯音乐模式下无需提供歌词；即便给了歌词模型也会忽略人声。

---

## 五、三种输入模式（云端自动识别，本地同理）

| 模式 | 触发方式 | 示例 |
|------|----------|------|
| **标签模式（推荐）** | 用 `<prompt>` / `<lyrics>` 标签 | `<prompt>轻快的夏日流行，木吉他+口哨</prompt>` |
| **自然语言模式** | 无标签、不像歌词 | `生成一首关于夏天和旅行的欢快流行歌` |
| **纯歌词模式** | 含 `[Verse]`/`[Chorus]` 等标记 | `[Verse 1]\nWalking down the street…` |

---

## 六、提示词示例（仅展示提示词本身）

下面只给出“你要写的内容”——音乐描述与歌词文本。标签模式用 `<prompt>` / `<lyrics>` 框住；纯音乐见 §4。

### 示例 1：带歌词的中文流行（标签模式）
- 音乐描述：`<prompt>C 大调温柔的原声情歌，80 BPM，女声，尼龙弦吉他</prompt>`
- 歌词：
  ```text
  <lyrics>[Verse 1]
  阳光穿过窗台
  新的一天开始

  [Chorus]
  我们是追梦的人
  我们是光</lyrics>
  ```

### 示例 2：英文动漫摇滚（摘自 examples/text2music/example_01.json 精简）
- 音乐描述：`An explosive, high-energy pop-rock track with a strong anime theme song feel. Driving rock beat, punchy drums, powerful male vocal, soaring chorus.`
- 歌词：
  ```text
  [Intro - Synth Brass Fanfare]

  [Verse 1]
  黑夜里的风吹过耳畔

  [Chorus]
  心电感应在震动间

  [Bridge]
  光影交错彼此的视线

  [Outro - Instrumental]
  ```

### 示例 3：纯音乐管弦配乐
- 音乐描述：`<prompt>史诗感管弦乐配乐，恢弘有力，sweeping strings and brass</prompt>`
- （配合 instrumental 开关，不写歌词）

### 示例 4：纯乐器 lo-fi
- 音乐描述：`<prompt>Dreamy lo-fi hip hop beat with vinyl crackle</prompt>`
- 歌词：`<lyrics>[inst]</lyrics>`

### 示例 5：自然语言模式（一句话，交给 LLM 自动扩写）
- `生成一首关于夏天和旅行的欢快流行歌`

### 示例 6：纯歌词模式（只给词，靠结构标签成歌）
```text
[Verse 1]
Walking down the street
Feeling the beat

[Chorus]
Dance with me tonight
```

---

## 七、速查清单（写之前对照）

- [ ] 风格 / 乐器 / 情绪 / 人声 是否至少写了 2~3 项？
- [ ] 歌词是否用了 `[Verse]` / `[Chorus]` 等结构标签并用空行分段？
- [ ] 纯音乐是否用了 `instrumental:true` 或 `[inst]`？
- [ ] 需要精准控制时，是否补了 `BPM` / 调式 / 拍号？
- [ ] 想偷懒 / 优化描述时，是否开了 `use_format` / `use_cot_caption`？
- [ ] 多语言歌词是否用 `vocal_language`（如 `zh` / `en` / `ja` / `fr` / `es` / `bn`）标明？

> 模型支持 **50+ 种语言**的歌词与描述；描述写得越具体、歌词结构越清晰，成歌越贴近预期。
