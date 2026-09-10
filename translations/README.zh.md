<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

**QQ群：875297969**

</div>

## 🌟 简介

AI Multilingual Video Translator 是一站式视频翻译本地化配音工具，能够一键生成 Netflix 级别的高质量字幕，告别生硬机翻，告别多行字幕，还能加上高质量的克隆配音，让全世界的知识能够跨越语言的障碍共享。

主要特点和功能：
- 🎥 使用 yt-dlp 从 Youtube 链接下载视频

- **🎙️ 使用 WhisperX 进行单词级和低幻觉字幕识别**

- **📝 使用 NLP 和 AI 进行字幕分割**

- **📚 自定义 + AI 生成术语库，保证翻译连贯性**

- **🔄 三步直译、反思、意译，实现影视级翻译质量**

- **✅ 按照 Netflix 标准检查单行长度，绝无双行字幕**

- **🗣️ 支持 GPT-SoVITS、Azure、OpenAI 等多种配音方案**

- 🚀 一键启动，在 streamlit 中一键出片

- 🌍 多语言支持就绪的 streamlit UI

- 📝 详细记录每步操作日志，支持随时中断和恢复进度

- 🔍 模型搜索选择器，自动从 API 获取完整模型列表，支持搜索筛选

- ⏯️ 任务控制 — 处理过程中可随时暂停、继续或停止

与同类项目相比的优势：**绝无多行字幕，最佳的翻译质量，无缝的配音体验**

### 语言支持

**输入语言支持：**

🇺🇸 英语 🤩  |  🇷🇺 俄语 😊  |  🇫🇷 法语 🤩  |  🇩🇪 德语 🤩  |  🇮🇹 意大利语 🤩  |  🇪🇸 西班牙语 🤩  |  🇯🇵 日语 😐  |  🇨🇳 中文* 😊

> *中文使用单独的标点增强后的 whisper 模型

**翻译语言支持所有语言，配音语言取决于选取的TTS。**

## 安装

> **注意:** 在 Windows 上使用 NVIDIA GPU 加速需要先完成以下步骤:
> 1. 安装 [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. 安装 [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. 将 `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` 添加到系统环境变量 PATH 中
> 4. 重启电脑

> **注意:** FFmpeg 是必需的，请通过包管理器安装：
> - Windows：```choco install ffmpeg```（通过 [Chocolatey](https://chocolatey.org/)）
> - macOS：```brew install ffmpeg```（通过 [Homebrew](https://brew.sh/)）
> - Linux：```sudo apt install ffmpeg```（Debian/Ubuntu）

### 方式一：使用 uv（推荐，无需安装 Anaconda）

[uv](https://docs.astral.sh/uv/) 会自动下载 Python 3.10 并创建隔离环境，你不需要自己安装 Python 或 Anaconda。

> **为什么用 uv 而不是 conda？**
> - Anaconda 安装包约 4GB，而 uv 只有约 30MB
> - uv 能自动下载并管理所需的 Python 版本，不会和系统已有的 Python 冲突
> - 安装速度快 10-100 倍（Rust 编写，并行下载）
> - 一条命令搞定，不需要学习 conda 命令

1. 克隆仓库

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. 一键安装（自动安装 uv + Python 3.10 + 所有依赖）

```bash
python setup_env.py
```

3. 启动应用

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

或者在 Windows 上双击 `OneKeyStart_uv.bat`。

### 方式二：使用 Conda

> ⚠️ **不推荐。** 此方式今后将不再维护，请使用上方的 uv（方式一）。

<details>
<summary>点击展开 Conda 安装步骤</summary>

1. 克隆仓库

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. 安装依赖（需要 `python=3.10`）

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. 启动应用

```bash
streamlit run st.py
```

</details>

### Docker
还可以选择使用 Docker（要求 CUDA 12.4 和 NVIDIA Driver 版本 >550），详见[Docker文档](/docs/pages/docs/docker.zh-CN.md)：

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## API
本项目支持 OpenAI-Like 格式的 api 和多种配音接口：
- LLM: `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ...（按质量排序；预算方案可尝试 `gemini-3-flash` 或 `gpt-5.4-mini`）
- WhisperX: 本地运行 WhisperX 或使用 302.ai API
- TTS: `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(你可以在 custom_tts.py 中自定义 TTS!)

> **注意：** AI Multilingual Video Translator 现已与 **[302.ai](https://302.ai)** 集成，**一个 API KEY** 即可同时支持 LLM、WhisperX 和 TTS！同时也支持完全本地部署，使用 Ollama 作为 LLM 和 Edge-TTS 作为配音，无需云端 API！

详细的安装、API 配置、批量说明可以参见文档：[English](/docs/pages/docs/start.en-US.md) | [简体中文](/docs/pages/docs/start.zh-CN.md)
