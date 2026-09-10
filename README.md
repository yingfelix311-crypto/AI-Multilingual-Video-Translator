# video translator

Translate video, prepare subtitles, and produce dubbed versions from one workspace.

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## Choose your starting point

| Input | Preparation | Result |
| --- | --- | --- |
| Video | Transcribe speech, segment and translate text, then build timed subtitles. | Subtitles and dubbing tasks |
| Video + translated SRT | Import subtitles, separate vocals, and review timing and speaker assignments. | Ready-to-dub timeline |
| Prepared timeline | Generate speech, assemble the audio track, mix and export. | Dubbed video |

## Run locally

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git video-translator
cd video-translator
python setup_env.py
```

**macOS / Linux**

```bash
.venv/bin/python run_webui.py
```

**Windows**

```powershell
.venv\Scripts\python run_webui.py
```

Open http://127.0.0.1:8501 after startup. On Windows, you can also use OneKeyStart.bat.

<details>
<summary>Requirements and GPU setup</summary>

Python 3.10 · Git · FFmpeg

> **Note:** For Windows users with NVIDIA GPU, follow these steps before installation:
> 1. Install [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Install [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Add `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` to your system PATH
> 4. Restart your computer

> **Note:** FFmpeg is required. Please install it via package managers:
> - Windows: ```choco install ffmpeg``` (via [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (via [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

</details>

## Configure the services

| Stage | Integration |
| --- | --- |
| Transcription and alignment | Qwen / DashScope; additional ASR backends are configured in config.yaml. |
| Translation | An OpenAI-compatible LLM endpoint, model name and API key. |
| Dubbing | NoizAI, ElevenLabs, Qwen, Azure, OpenAI, GPT-SoVITS and other configured TTS backends. |

Available languages and voice-cloning options depend on the selected providers.

## Project guide

| File | Purpose |
| --- | --- |
| [run_webui.py](/run_webui.py) | Web interface launcher |
| [config.yaml](/config.yaml) | Processing and subtitle settings |
| [custom_terms.xlsx](/custom_terms.xlsx) | Custom terminology |
| [core/](/core/) | Pipeline steps and audio processing |
| [webui/](/webui/) | Web interface and task controls |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Colab notebook |

<details>
<summary>Installation and API details</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
