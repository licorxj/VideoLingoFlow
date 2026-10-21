# Suno 音乐提示词（Prompt）撰写指南与示例

> 适用：Suno v3.5 / v4 / v4.5（Web 与 API 均适用）
> 核心输入：**Style of Music（风格描述）** 与 **Lyrics（歌词）** 两个字段

---

## 一、两大输入字段

| 字段 | 作用 | 建议长度 |
|------|------|----------|
| **Style of Music**（风格描述） | 决定曲风、乐器、情绪、人声、节奏 | 120~400 字符（v4.5 上限 1000） |
| **Lyrics**（歌词） | 决定唱什么、段落结构 | 自定义模式必须填写；纯音乐写 `[Instrumental]` |

Simple 模式只有一句话描述框（相当于只有 Style）；Custom 模式两个都可控制。

---

## 二、风格描述（Style）撰写规则

### 2.1 推荐要素（按优先级）
1. **流派 / 风格**（必写）：pop, rock, synthwave, lo-fi hip hop, city pop, folk, orchestral, EDM, trap, R&B, jazz fusion…
2. **情绪 / 氛围**：uplifting, melancholic, dreamy, epic, nostalgic, cozy, energetic…
3. **乐器 / 编排**：acoustic guitar, synth arpeggios, 808 bass, string quartet, saxophone, analog drums…
4. **人声**：male vocals, female vocals, duet, choir, raspy voice, whispery vocals, rap…
5. **节奏 / 速度**（可选）：slow ballad, mid-tempo, 120 BPM, half-time groove…
6. **制作质感**（可选）：lo-fi, polished studio production, live session feel, 80s retro production…

### 2.2 写法要点
- 用**逗号分隔的短语**，不要写成完整句子；把最重要的风格放最前面。
- ❌ 差：`一首好听的歌`
- ✅ 好：`dreamy synthwave, nostalgic 80s retro production, warm analog synth pads, steady mid-tempo beat, male vocals`
- 避免出现**歌手 / 艺人真名**（会被过滤或忽略），用风格特征描述代替（如 `gritty rock vocals in the style of 90s grunge`）。
- 想要的东西就写出来，没写的交给模型发挥；描述越长控制力越强，但也可能压缩模型自由度。

### 2.3 Exclude Styles（排除风格）
v4.5 支持反向控制：在 Exclude Styles 字段填不想出现的元素，如 `heavy metal, screaming, distorted guitar`。

---

## 三、歌词（Lyrics）撰写规则

### 3.1 结构标签（Meta Tags）
用方括号标注段落，模型据此组织歌曲结构：

| 标签 | 含义 |
|------|------|
| `[Intro]` | 前奏 |
| `[Verse 1]` / `[Verse 2]` | 主歌 |
| `[Pre-Chorus]` | 预副歌 |
| `[Chorus]` | 副歌 |
| `[Post-Chorus]` | 尾副歌 |
| `[Bridge]` | 桥段 |
| `[Hook]` | 主题句 / 记忆点 |
| `[Drop]` | 电子乐 Drop 段 |
| `[Instrumental]` / `[Instrumental Break]` | 间奏（无人声） |
| `[Guitar Solo]` / `[Saxophone Solo]` | 器乐独奏段 |
| `[Outro]` | 尾奏 |
| `[End]` / `[Fade Out]` | 收尾（渐弱） |

### 3.2 行内表演标记
- **圆括号**：和声 / 背景人声 / 即兴词 —— `(ooh yeah)` `(echo: forever)`
- **方括号行内**：演唱方式提示 —— `[whispered]` `[powerful vocals]` `[rap]`
- 段落之间**空行分隔**；副歌重复时歌词可重复写，也可只写一次。

### 3.3 人声方向
可在歌词开头或段落标签中标注：`[Female Verse]` `[Male Chorus]` `[Duet]`；对唱可用 `(He: ...)` `(She: ...)` 行内标记。

### 3.4 纯音乐（Instrumental）
- Lyrics 字段填 `[Instrumental]`（或留空并在 Style 中说明）；
- Style 描述强调器乐：`epic orchestral film score, no vocals, sweeping strings and brass, cinematic percussion`。

---

## 四、示例

### 示例 1：中文流行（Custom 模式）
- Style：`温暖治愈的中文流行，原声木吉他为主，轻盈的鼓刷与贝斯，女声清澈，80 BPM，副歌加入弦乐铺底`
- Lyrics：
```text
[Verse 1]
阳光穿过窗台
新的一天开始

[Chorus]
我们是追梦的人
我们是光

[Outro]
[Fade Out]
```

### 示例 2：英文 Synthwave
- Style：`dreamy synthwave, nostalgic 80s retro production, warm analog synth pads, punchy electronic drums, male vocals, 110 BPM`
- Lyrics：
```text
[Verse 1]
Neon lights on the boulevard

[Chorus]
We run through the night
Chasing the fading light

[Outro]
[Instrumental]
[Fade Out]
```

### 示例 3：纯音乐配乐
- Style：`epic orchestral film score, no vocals, sweeping strings, heroic brass, cinematic percussion, gradual build`
- Lyrics：`[Instrumental]`

### 示例 4：说唱
- Style：`hard-hitting boom bap hip hop, dusty vinyl drums, deep 808 bass, confident male rap, old school 90s flavor`
- Lyrics：
```text
[Intro]
[Instrumental Break]

[Verse 1]
[Rap] ...
```

---

## 五、速查清单

- [ ] Style 是否包含流派 + 情绪 + 人声（至少 3 项）？是否用逗号短语？
- [ ] 歌词是否用 `[Verse]` / `[Chorus]` 等结构标签并空行分段？
- [ ] 背景和声是否用 `( )` 圆括号？
- [ ] 纯音乐是否写了 `[Instrumental]`？
- [ ] 是否避免了艺人真名？
- [ ] 需要排除的元素是否写进 Exclude Styles？
