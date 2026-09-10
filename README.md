<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 Overview

AI Multilingual Video Translator is an all-in-one video translation, localization, and dubbing tool aimed at generating Netflix-quality subtitles. It eliminates stiff machine translations and multi-line subtitles while adding high-quality dubbing, enabling global knowledge sharing across language barriers.

Key features:
- 🎥 YouTube video download via yt-dlp

- **🎙️ Word-level and Low-illusion subtitle recognition with WhisperX**

- **📝 NLP and AI-powered subtitle segmentation**

- **📚 Custom + AI-generated terminology for coherent translation**

- **🔄 3-step Translate-Reflect-Adaptation for cinematic quality**

- **✅ Netflix-standard, Single-line subtitles Only**

- **🗣️ Dubbing with GPT-SoVITS, Azure, OpenAI, and more**

- 🚀 One-click startup and processing in Streamlit

- 🌍 Multi-language support in Streamlit UI

- 📝 Detailed logging with progress resumption

- 🔍 Model searchbox with API auto-fetch — search and filter from your provider's full model list

- ⏯️ Task control — pause, resume, or stop processing at any step

Difference from similar projects: **Single-line subtitles only, superior translation quality, seamless dubbing experience**

### Language Support

**Input Language Support(more to come):**

🇺🇸 English 🤩 | 🇷🇺 Russian 😊 | 🇫🇷 French 🤩 | 🇩🇪 German 🤩 | 🇮🇹 Italian 🤩 | 🇪🇸 Spanish 🤩 | 🇯🇵 Japanese 😐 | 🇨🇳 Chinese* 😊

> *Chinese uses a separate punctuation-enhanced whisper model, for now...

**Translation supports all languages, while dubbing language depends on the chosen TTS method.**

## Installation

> **Note:** For Windows users with NVIDIA GPU, follow these steps before installation:
> 1. Install [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Install [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Add `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` to your system PATH
> 4. Restart your computer

> **Note:** FFmpeg is required. Please install it via package managers:
> - Windows: ```choco install ffmpeg``` (via [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (via [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

### Option A: Using uv (Recommended, No Anaconda Required)

[uv](https://docs.astral.sh/uv/) automatically downloads Python 3.10 and creates an isolated environment — no need to install Python or Anaconda yourself.

1. Clone the repository

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. One-command setup (installs uv + Python 3.10 + all dependencies)

```bash
python setup_env.py
```

3. Start the application

```bash
.venv\Scripts\python run_webui.py        # Windows
.venv/bin/python run_webui.py            # macOS / Linux
```

Or double-click `OneKeyStart.bat` on Windows.

### Option B: Using Conda

> ⚠️ **Not recommended.** This method will not be maintained going forward. Please use uv (Option A) above.

<details>
<summary>Click to expand Conda installation steps</summary>

1. Clone the repository

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Install dependencies (requires `python=3.10`)

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. Start the application

```bash
python run_webui.py
```

</details>

### Docker
Alternatively, you can use Docker (requires CUDA 12.4 and NVIDIA Driver version >550), see [Docker docs](/docs/pages/docs/docker.en-US.md):

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## APIs
AI Multilingual Video Translator supports OpenAI-Like API format and various TTS interfaces:
- LLM: `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ... (sorted by quality; for budget options try `gemini-3-flash` or `gpt-5.4-mini`)
- WhisperX: Run whisperX (large-v3) locally or use 302.ai API
- TTS: `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(You can modify your own TTS in custom_tts.py!)

> **Note:** AI Multilingual Video Translator works with **[302.ai](https://302.ai)** - one API key for all services (LLM, WhisperX, TTS). Or run locally with Ollama and Edge-TTS for free, no API needed!

For detailed installation, API configuration, and batch mode instructions, please refer to the documentation: [English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
