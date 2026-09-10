# video translator

Transcribe vídeos, traduce subtítulos y genera versiones dobladas desde un mismo espacio de trabajo.

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## Elige el punto de partida

| Entrada | Preparación | Resultado |
| --- | --- | --- |
| Vídeo | Transcripción, segmentación y traducción con marcas de tiempo. | Subtítulos y tareas de doblaje |
| Vídeo + SRT traducido | Importación, separación de voz y revisión de tiempos y hablantes. | Línea de tiempo preparada |
| Línea de tiempo preparada | Síntesis, montaje de audio, mezcla y exportación. | Vídeo doblado |

## Ejecución local

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

Abre http://127.0.0.1:8501 al iniciar. En Windows también puedes usar OneKeyStart.bat.

<details>
<summary>Requisitos y configuración de GPU</summary>

Python 3.10 · Git · FFmpeg

> **Nota:** Para usuarios de Windows con GPU NVIDIA, sigue estos pasos antes de la instalación:
> 1. Instala [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Instala [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Agrega `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` a tu PATH del sistema
> 4. Reinicia tu computadora

> **Nota:** Se requiere FFmpeg. Por favor, instálalo a través de gestores de paquetes:
> - Windows: ```choco install ffmpeg``` (vía [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (vía [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

</details>

## Configuración de servicios

| Etapa | Integración |
| --- | --- |
| Transcripción y alineación | Qwen / DashScope; otros motores ASR se configuran en config.yaml. |
| Traducción | Endpoint compatible con OpenAI, nombre del modelo y clave API. |
| Doblaje | NoizAI, ElevenLabs, Qwen, Azure, OpenAI, GPT-SoVITS y otros motores TTS configurados. |

Los idiomas y la clonación de voz dependen del proveedor seleccionado.

## Guía de archivos

| Archivo | Uso |
| --- | --- |
| [run_webui.py](/run_webui.py) | Lanzador de la interfaz web |
| [config.yaml](/config.yaml) | Configuración de procesamiento y subtítulos |
| [custom_terms.xlsx](/custom_terms.xlsx) | Terminología personalizada |
| [core/](/core/) | Procesamiento de texto y audio |
| [webui/](/webui/) | Interfaz web y controles de tareas |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Cuaderno Colab |

<details>
<summary>Detalles de instalación y API</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
