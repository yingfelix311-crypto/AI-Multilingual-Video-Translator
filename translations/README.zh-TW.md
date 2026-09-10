<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 概述

AI Multilingual Video Translator 是一個全方位的影片翻譯、本地化和配音工具，旨在生成 Netflix 品質的字幕。它消除了機器翻譯的生硬感和多行字幕，同時提供高品質配音，實現跨越語言障礙的全球知識共享。

主要功能：
- 🎥 通過 yt-dlp 下載 YouTube 影片

- **🎙️ 使用 WhisperX 進行詞級別和低幻覺字幕識別**

- **📝 基於 NLP 和 AI 的字幕分段**

- **📚 自定義 + AI 生成術語庫確保翻譯一致性**

- **🔄 三步驟翻譯-反思-調適實現影院級品質**

- **✅ Netflix 標準，僅單行字幕**

- **🗣️ 使用 GPT-SoVITS、Azure、OpenAI 等進行配音**

- 🚀 在 Streamlit 中一鍵啟動和處理

- 🌍 Streamlit UI 多語言支持

- 📝 詳細日誌記錄和進度恢復

- 🔍 模型搜尋選擇器，自動從 API 獲取完整模型清單，支援搜尋篩選

- ⏯️ 任務控制 — 處理過程中可隨時暫停、繼續或停止

與類似項目的區別：**僅單行字幕、更優質的翻譯、無縫配音體驗**

### 語言支持

**輸入語言支持（更多語言即將推出）：**

🇺🇸 英語 🤩 | 🇷🇺 俄語 😊 | 🇫🇷 法語 🤩 | 🇩🇪 德語 🤩 | 🇮🇹 義大利語 🤩 | 🇪🇸 西班牙語 🤩 | 🇯🇵 日語 😐 | 🇨🇳 中文* 😊

> *中文目前使用單獨的標點增強版 whisper 模型...

**翻譯支持所有語言，配音語言則取決於所選的 TTS 方法。**

## 安裝

> **注意：** Windows 用戶如使用 NVIDIA GPU，請在安裝前執行以下步驟：
> 1. 安裝 [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. 安裝 [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. 將 `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` 添加到系統 PATH
> 4. 重啟電腦

> **注意：** 需要安裝 FFmpeg。請通過包管理器安裝：
> - Windows：```choco install ffmpeg```（通過 [Chocolatey](https://chocolatey.org/)）
> - macOS：```brew install ffmpeg```（通過 [Homebrew](https://brew.sh/)）
> - Linux：```sudo apt install ffmpeg```（Debian/Ubuntu）

### 方式一：使用 uv（推薦）

[uv](https://docs.astral.sh/uv/) 會自動下載 Python 3.10 並建立隔離環境，無需手動安裝 Python 或 Anaconda。

1. 複製倉庫

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. 一鍵安裝（自動安裝 uv + Python 3.10 + 所有依賴）

```bash
python setup_env.py
```

3. 啟動應用

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

或在 Windows 上雙擊 `OneKeyStart_uv.bat`。

### 方式二：使用 Conda

> ⚠️ **不推薦。** 此方式今後將不再維護，請使用上方的 uv（方式一）。

<details>
<summary>點擊展開 Conda 安裝步驟</summary>

1. 複製倉庫

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. 安裝依賴（需要 `python=3.10`）

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. 啟動應用

```bash
streamlit run st.py
```

</details>

### Docker
或者，您可以使用 Docker（需要 CUDA 12.4 和 NVIDIA 驅動版本 >550），參見 [Docker 文檔](/docs/pages/docs/docker.en-US.md)：

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## APIs
AI Multilingual Video Translator 支持 OpenAI 格式的 API 和各種 TTS 接口：
- LLM：`claude-sonnet-4.6`、`gpt-5.4`、`gemini-3.1-pro`、`deepseek-v3`、`grok-4.1`、...（按品質排序；預算方案可嘗試 `gemini-3-flash` 或 `gpt-5.4-mini`）
- WhisperX：本地運行 whisperX 或使用 302.ai API
- TTS：`azure-tts`、`openai-tts`、`siliconflow-fishtts`、**`fish-tts`**、`GPT-SoVITS`、`edge-tts`、`*custom-tts`（您可以在 custom_tts.py 中修改自己的 TTS！）

> **注意：** AI Multilingual Video Translator 與 **[302.ai](https://302.ai)** 合作 - 一個 API 密鑰即可使用所有服務（LLM、WhisperX、TTS）。或者使用 Ollama 和 Edge-TTS 在本地免費運行，無需 API！

詳細安裝、API 配置和批處理模式說明，請參閱文檔：[English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
