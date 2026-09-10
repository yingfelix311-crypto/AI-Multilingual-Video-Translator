<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 概要

AI Multilingual Video Translatorは、Netflixクオリティの字幕を生成することを目的とした、オールインワンの動画翻訳、ローカライゼーション、吹き替えツールです。機械的な翻訳や複数行の字幕を排除し、高品質な吹き替えを追加することで、言語の壁を越えた世界的な知識共有を可能にします。

主な機能：
- 🎥 yt-dlpによるYouTube動画のダウンロード

- **🎙️ WhisperXによる単語レベルの低誤認識字幕認識**

- **📝 NLPとAIを活用した字幕セグメンテーション**

- **📚 一貫性のある翻訳のためのカスタム＋AI生成用語**

- **🔄 映画品質のための3ステップ（翻訳-反映-適応）プロセス**

- **✅ Netflixスタンダードの1行字幕のみ**

- **🗣️ GPT-SoVITS、Azure、OpenAIなどによる吹き替え**

- 🚀 Streamlitでのワンクリック起動と処理

- 🌍 Streamlit UIの多言語サポート

- 📝 進捗再開機能付きの詳細なログ記録

- 🔍 モデル検索セレクター — APIからモデル一覧を自動取得、検索・フィルター対応

- ⏯️ タスクコントロール — 処理中いつでも一時停止・再開・中止が可能

類似プロジェクトとの違い：**1行字幕のみ、優れた翻訳品質、シームレスな吹き替え体験**

### 言語サポート

**入力言語サポート（今後追加予定）：**

🇺🇸 英語 🤩 | 🇷🇺 ロシア語 😊 | 🇫🇷 フランス語 🤩 | 🇩🇪 ドイツ語 🤩 | 🇮🇹 イタリア語 🤩 | 🇪🇸 スペイン語 🤩 | 🇯🇵 日本語 😐 | 🇨🇳 中国語* 😊

> *中国語は現在、句読点強化されたwhisperモデルを使用しています。

**翻訳はすべての言語に対応していますが、吹き替えの言語は選択したTTS方式によって異なります。**

## インストール

> **注意：** NVIDIA GPUを搭載したWindowsユーザーは、インストール前に以下の手順を実行してください：
> 1. [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)をインストール
> 2. [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)をインストール
> 3. `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6`をシステムPATHに追加
> 4. コンピュータを再起動

> **注意：** FFmpegが必要です。パッケージマネージャーを使用してインストールしてください：
> - Windows: ```choco install ffmpeg``` ([Chocolatey](https://chocolatey.org/)経由)
> - macOS: ```brew install ffmpeg``` ([Homebrew](https://brew.sh/)経由)
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

### オプションA：uvを使用（推奨）

[uv](https://docs.astral.sh/uv/)はPython 3.10を自動的にダウンロードし、隔離された環境を作成します。PythonやAnacondaを手動でインストールする必要はありません。

1. リポジトリをクローン

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. ワンコマンドセットアップ（uv + Python 3.10 + すべての依存関係を自動インストール）

```bash
python setup_env.py
```

3. アプリケーションの起動

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

またはWindowsで`OneKeyStart_uv.bat`をダブルクリック。

### オプションB：Condaを使用

> ⚠️ **非推奨。** この方法は今後メンテナンスされません。上記の uv（オプションA）をご利用ください。

<details>
<summary>クリックしてCondaのインストール手順を展開</summary>

1. リポジトリをクローン

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. 依存関係のインストール（`python=3.10`が必要）

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. アプリケーションの起動

```bash
streamlit run st.py
```

</details>

### Docker
または、Docker（CUDA 12.4とNVIDIAドライバーバージョン>550が必要）を使用することもできます。[Dockerドキュメント](/docs/pages/docs/docker.en-US.md)を参照してください：

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## API
AI Multilingual Video TranslatorはOpenAIライクなAPI形式と様々なTTSインターフェースをサポートしています：
- LLM: `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ... (品質順；予算重視なら `gemini-3-flash` または `gpt-5.4-mini`)
- WhisperX: ローカルでwhisperXを実行するか302.ai APIを使用
- TTS: `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(custom_tts.pyで独自のTTSを修正可能！)

> **注意：** AI Multilingual Video Translatorは**[302.ai](https://302.ai)**と連携しています - すべてのサービス（LLM、WhisperX、TTS）に1つのAPIキーで対応。またはOllamaとEdge-TTSを使用してローカルで無料で実行可能で、APIは不要です！

詳細なインストール方法、API設定、バッチモードの説明については、ドキュメントを参照してください：[English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
