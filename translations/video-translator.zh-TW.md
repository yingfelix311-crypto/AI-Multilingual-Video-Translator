# video translator

在同一個工作區完成影片轉寫、字幕翻譯、時間軸校對與配音輸出。

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## 從你的素材開始

| 已有素材 | 處理方式 | 輸出 |
| --- | --- | --- |
| 影片 | 語音辨識、分句翻譯並產生帶時間軸的字幕。 | 字幕與配音任務 |
| 影片 + 譯文 SRT | 匯入字幕、分離人聲並檢查時間軸與人物標記。 | 可配音的時間軸 |
| 已準備的時間軸 | 合成語音、拼接音軌、混音並匯出。 | 配音影片 |

## 本機啟動

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

啟動後開啟 http://127.0.0.1:8501。Windows 亦可使用 OneKeyStart.bat。

<details>
<summary>執行依賴與 GPU 設定</summary>

Python 3.10 · Git · FFmpeg

> **注意：** Windows 用戶如使用 NVIDIA GPU，請在安裝前執行以下步驟：
> 1. 安裝 [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. 安裝 [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. 將 `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` 添加到系統 PATH
> 4. 重啟電腦

> **注意：** 需要安裝 FFmpeg。請通過包管理器安裝：
> - Windows：```choco install ffmpeg```（通過 [Chocolatey](https://chocolatey.org/)）
> - macOS：```brew install ffmpeg```（通過 [Homebrew](https://brew.sh/)）
> - Linux：```sudo apt install ffmpeg```（Debian/Ubuntu）

</details>

## 連接所需服務

| 處理環節 | 介面設定 |
| --- | --- |
| 轉寫與對齊 | Qwen / DashScope；其他 ASR 後端透過 config.yaml 設定。 |
| 字幕翻譯 | 設定相容 OpenAI 格式的模型介面、模型名稱與 API Key。 |
| 語音配音 | 可設定 NoizAI、ElevenLabs、Qwen、Azure、OpenAI、GPT-SoVITS 等 TTS 後端。 |

可用語言及聲音克隆能力取決於所選服務。

## 專案檔案導覽

| 檔案 | 用途 |
| --- | --- |
| [run_webui.py](/run_webui.py) | 網頁介面啟動入口 |
| [config.yaml](/config.yaml) | 處理流程與字幕設定 |
| [custom_terms.xlsx](/custom_terms.xlsx) | 自訂術語表 |
| [core/](/core/) | 轉寫、翻譯與音訊處理 |
| [webui/](/webui/) | 網頁介面與任務控制 |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Colab 筆記本 |

<details>
<summary>安裝與介面設定詳情</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
