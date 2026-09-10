# video translator

在一个工作区完成视频转写、字幕翻译、时间轴校对与配音成片。

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## 从你的素材开始

| 已有素材 | 处理方式 | 得到什么 |
| --- | --- | --- |
| 只有视频 | 识别人声、分句翻译，并生成带时间轴的字幕。 | 字幕与配音任务 |
| 视频 + 译文 SRT | 导入字幕、分离人声，检查时间轴与人物标记。 | 可配音的时间轴 |
| 已准备好的时间轴 | 合成语音、拼接音轨、混音并导出。 | 配音视频 |

## 本地启动

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

启动后打开 http://127.0.0.1:8501。Windows 也可以使用 OneKeyStart.bat 启动。

<details>
<summary>运行依赖与 GPU 设置</summary>

Python 3.10 · Git · FFmpeg

> **注意:** 在 Windows 上使用 NVIDIA GPU 加速需要先完成以下步骤:
> 1. 安装 [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. 安装 [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. 将 `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` 添加到系统环境变量 PATH 中
> 4. 重启电脑

> **注意:** FFmpeg 是必需的，请通过包管理器安装：
> - Windows：```choco install ffmpeg```（通过 [Chocolatey](https://chocolatey.org/)）
> - macOS：```brew install ffmpeg```（通过 [Homebrew](https://brew.sh/)）
> - Linux：```sudo apt install ffmpeg```（Debian/Ubuntu）

</details>

## 连接所需服务

| 处理环节 | 接口配置 |
| --- | --- |
| 转写与对齐 | Qwen / DashScope；其他 ASR 后端通过 config.yaml 配置。 |
| 字幕翻译 | 配置兼容 OpenAI 格式的模型接口、模型名与 API Key。 |
| 语音配音 | 可配置 NoizAI、ElevenLabs、Qwen、Azure、OpenAI、GPT-SoVITS 等 TTS 后端。 |

可用语言及声音克隆能力由所选服务决定。

## 项目文件导航

| 文件 | 用途 |
| --- | --- |
| [run_webui.py](/run_webui.py) | 网页界面启动入口 |
| [config.yaml](/config.yaml) | 处理流程与字幕设置 |
| [custom_terms.xlsx](/custom_terms.xlsx) | 自定义术语表 |
| [core/](/core/) | 转写、翻译及音频处理步骤 |
| [webui/](/webui/) | 网页界面与任务控制 |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Colab 笔记本 |

<details>
<summary>安装与接口配置详情</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
