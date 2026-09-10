# video translator

Распознавайте речь, переводите субтитры и создавайте озвученные версии видео в одном рабочем пространстве.

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## Выберите исходные материалы

| Вход | Подготовка | Результат |
| --- | --- | --- |
| Видео | Распознавание речи, сегментация, перевод и временные метки. | Субтитры и задания озвучки |
| Видео + переведённый SRT | Импорт, отделение голоса, проверка тайминга и говорящих. | Готовая временная шкала |
| Готовая временная шкала | Синтез речи, сборка аудио, сведение и экспорт. | Озвученное видео |

## Локальный запуск

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

После запуска откройте http://127.0.0.1:8501. В Windows также доступен OneKeyStart.bat.

<details>
<summary>Зависимости и настройка GPU</summary>

Python 3.10 · Git · FFmpeg

> **Примечание:** Для пользователей Windows с GPU NVIDIA выполните следующие шаги перед установкой:
> 1. Установите [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Установите [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Добавьте `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` в системный PATH
> 4. Перезагрузите компьютер

> **Примечание:** Требуется FFmpeg. Установите его через менеджеры пакетов:
> - Windows: ```choco install ffmpeg``` (через [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (через [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

</details>

## Настройка сервисов

| Этап | Интеграция |
| --- | --- |
| Распознавание и выравнивание | Qwen / DashScope; другие ASR настраиваются в config.yaml. |
| Перевод | Совместимый с OpenAI API, имя модели и API-ключ. |
| Озвучка | NoizAI, ElevenLabs, Qwen, Azure, OpenAI, GPT-SoVITS и другие настроенные TTS. |

Доступные языки и клонирование голоса зависят от выбранных сервисов.

## Навигация по файлам

| Файл | Назначение |
| --- | --- |
| [run_webui.py](/run_webui.py) | Запуск веб-интерфейса |
| [config.yaml](/config.yaml) | Настройки обработки и субтитров |
| [custom_terms.xlsx](/custom_terms.xlsx) | Пользовательская терминология |
| [core/](/core/) | Обработка текста и аудио |
| [webui/](/webui/) | Веб-интерфейс и управление задачами |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Блокнот Colab |

<details>
<summary>Установка и настройка API</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
