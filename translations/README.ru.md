<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 Обзор

AI Multilingual Video Translator - это универсальный инструмент для перевода, локализации и дубляжа видео, направленный на создание субтитров качества Netflix. Он устраняет механические переводы и многострочные субтитры, добавляя высококачественный дубляж, что позволяет делиться знаниями по всему миру, преодолевая языковые барьеры.

Ключевые особенности:
- 🎥 Загрузка видео с YouTube через yt-dlp

- **🎙️ Пословное распознавание субтитров с низким уровнем искажений с помощью WhisperX**

- **📝 Сегментация субтитров на основе NLP и ИИ**

- **📚 Пользовательская + ИИ-генерируемая терминология для согласованного перевода**

- **🔄 3-этапный процесс Перевод-Осмысление-Адаптация для кинематографического качества**

- **✅ Только однострочные субтитры стандарта Netflix**

- **🗣️ Дубляж с помощью GPT-SoVITS, Azure, OpenAI и других**

- 🚀 Запуск и обработка в один клик в Streamlit

- 🌍 Многоязычная поддержка в интерфейсе Streamlit

- 📝 Подробное логирование с возможностью возобновления прогресса

- 🔍 Селектор моделей с поиском — автоматическое получение полного списка моделей от вашего API-провайдера

- ⏯️ Управление задачами — пауза, возобновление или остановка обработки на любом этапе

Отличие от похожих проектов: **Только однострочные субтитры, превосходное качество перевода, безупречный опыт дубляжа**

### Поддержка языков

**Поддержка входных языков (будет добавлено больше):**

🇺🇸 Английский 🤩 | 🇷🇺 Русский 😊 | 🇫🇷 Французский 🤩 | 🇩🇪 Немецкий 🤩 | 🇮🇹 Итальянский 🤩 | 🇪🇸 Испанский 🤩 | 🇯🇵 Японский 😐 | 🇨🇳 Китайский* 😊

> *Китайский пока использует отдельную модель whisper с улучшенной пунктуацией...

**Перевод поддерживает все языки, в то время как язык дубляжа зависит от выбранного метода TTS.**

## Установка

> **Примечание:** Для пользователей Windows с GPU NVIDIA выполните следующие шаги перед установкой:
> 1. Установите [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Установите [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Добавьте `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` в системный PATH
> 4. Перезагрузите компьютер

> **Примечание:** Требуется FFmpeg. Установите его через менеджеры пакетов:
> - Windows: ```choco install ffmpeg``` (через [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (через [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

### Вариант А: Используя uv (Рекомендуется)

[uv](https://docs.astral.sh/uv/) автоматически загружает Python 3.10 и создает изолированную среду. Не нужно устанавливать Python или Anaconda вручную.

1. Клонируйте репозиторий

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Установка одной командой (устанавливает uv + Python 3.10 + все зависимости)

```bash
python setup_env.py
```

3. Запустите приложение

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

Или дважды щелкните `OneKeyStart_uv.bat` в Windows.

### Вариант Б: Используя Conda

> ⚠️ **Не рекомендуется.** Этот метод больше не будет поддерживаться. Пожалуйста, используйте uv (Вариант А) выше.

<details>
<summary>Нажмите, чтобы развернуть шаги установки с Conda</summary>

1. Клонируйте репозиторий

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Установите зависимости (требуется `python=3.10`)

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. Запустите приложение

```bash
streamlit run st.py
```

</details>

### Docker
Альтернативно, вы можете использовать Docker (требуется CUDA 12.4 и версия драйвера NVIDIA >550), см. [документацию Docker](/docs/pages/docs/docker.en-US.md):

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## API
AI Multilingual Video Translator поддерживает формат API, подобный OpenAI, и различные интерфейсы TTS:
- LLM: `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ... (отсортировано по качеству; бюджетные варианты: `gemini-3-flash` или `gpt-5.4-mini`)
- WhisperX: Запускайте whisperX локально или используйте API 302.ai
- TTS: `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(Вы можете модифицировать свой собственный TTS в custom_tts.py!)

> **Примечание:** AI Multilingual Video Translator работает с **[302.ai](https://302.ai)** - один API-ключ для всех сервисов (LLM, WhisperX, TTS). Или запускайте локально с Ollama и Edge-TTS бесплатно, без необходимости в API!

Для подробных инструкций по установке, настройке API и пакетному режиму обратитесь к документации: [English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
