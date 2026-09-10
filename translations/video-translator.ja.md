# video translator

動画の文字起こし、字幕翻訳、タイミング調整、吹き替え出力を一つのワークスペースで行います。

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## 素材に合わせた処理

| 入力 | 準備 | 出力 |
| --- | --- | --- |
| 動画 | 音声認識、文の分割、翻訳、タイムスタンプ付き字幕の生成。 | 字幕と吹き替えタスク |
| 動画 + 翻訳済み SRT | 字幕の取り込み、音声分離、タイミングと話者の確認。 | 吹き替え用タイムライン |
| 準備済みタイムライン | 音声合成、音声トラックの結合、ミックス、書き出し。 | 吹き替え動画 |

## ローカルで起動

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

起動後に http://127.0.0.1:8501 を開きます。Windows では OneKeyStart.bat も利用できます。

<details>
<summary>必要な環境と GPU 設定</summary>

Python 3.10 · Git · FFmpeg

> **注意：** NVIDIA GPUを搭載したWindowsユーザーは、インストール前に以下の手順を実行してください：
> 1. [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)をインストール
> 2. [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)をインストール
> 3. `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6`をシステムPATHに追加
> 4. コンピュータを再起動

> **注意：** FFmpegが必要です。パッケージマネージャーを使用してインストールしてください：
> - Windows: ```choco install ffmpeg``` ([Chocolatey](https://chocolatey.org/)経由)
> - macOS: ```brew install ffmpeg``` ([Homebrew](https://brew.sh/)経由)
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

</details>

## サービスの設定

| 処理 | 接続先 |
| --- | --- |
| 文字起こしとアラインメント | Qwen / DashScope。その他の ASR は config.yaml で設定します。 |
| 字幕翻訳 | OpenAI 互換エンドポイント、モデル名、API キー。 |
| 吹き替え | NoizAI、ElevenLabs、Qwen、Azure、OpenAI、GPT-SoVITS などの TTS。 |

対応言語と音声クローン機能は選択したサービスによって異なります。

## ファイルガイド

| ファイル | 用途 |
| --- | --- |
| [run_webui.py](/run_webui.py) | Web UI の起動 |
| [config.yaml](/config.yaml) | 処理と字幕の設定 |
| [custom_terms.xlsx](/custom_terms.xlsx) | カスタム用語集 |
| [core/](/core/) | 文字起こし・翻訳・音声処理 |
| [webui/](/webui/) | Web UI とタスク管理 |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Colab ノートブック |

<details>
<summary>インストールと API 設定</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
