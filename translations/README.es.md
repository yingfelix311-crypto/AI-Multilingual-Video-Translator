<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 Descripción General

AI Multilingual Video Translator es una herramienta todo en uno para traducción, localización y doblaje de videos, diseñada para generar subtítulos de calidad Netflix. Elimina las traducciones mecánicas y los subtítulos de múltiples líneas mientras agrega doblaje de alta calidad, permitiendo compartir conocimiento globalmente a través de las barreras del idioma.

Características principales:
- 🎥 Descarga de videos de YouTube mediante yt-dlp

- **🎙️ Reconocimiento de subtítulos a nivel de palabra y baja ilusión con WhisperX**

- **📝 Segmentación de subtítulos impulsada por NLP e IA**

- **📚 Terminología personalizada + generada por IA para una traducción coherente**

- **🔄 Proceso de 3 pasos Traducción-Reflexión-Adaptación para calidad cinematográfica**

- **✅ Solo subtítulos de una línea, estándar Netflix**

- **🗣️ Doblaje con GPT-SoVITS, Azure, OpenAI y más**

- 🚀 Inicio y procesamiento con un clic en Streamlit

- 🌍 Soporte multilingüe en la interfaz de Streamlit

- 📝 Registro detallado con reanudación de progreso

- 🔍 Selector de modelos con búsqueda — obtiene automáticamente la lista completa de modelos desde tu API

- ⏯️ Control de tareas — pausa, reanuda o detén el procesamiento en cualquier paso

Diferencia con proyectos similares: **Solo subtítulos de una línea, calidad superior de traducción, experiencia de doblaje perfecta**

### Soporte de Idiomas

**Soporte de idiomas de entrada (más por venir):**

🇺🇸 Inglés 🤩 | 🇷🇺 Ruso 😊 | 🇫🇷 Francés 🤩 | 🇩🇪 Alemán 🤩 | 🇮🇹 Italiano 🤩 | 🇪🇸 Español 🤩 | 🇯🇵 Japonés 😐 | 🇨🇳 Chino* 😊

> *El chino utiliza un modelo whisper mejorado con puntuación por ahora...

**La traducción admite todos los idiomas, mientras que el idioma del doblaje depende del método TTS elegido.**

## Instalación

> **Nota:** Para usuarios de Windows con GPU NVIDIA, sigue estos pasos antes de la instalación:
> 1. Instala [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Instala [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Agrega `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` a tu PATH del sistema
> 4. Reinicia tu computadora

> **Nota:** Se requiere FFmpeg. Por favor, instálalo a través de gestores de paquetes:
> - Windows: ```choco install ffmpeg``` (vía [Chocolatey](https://chocolatey.org/))
> - macOS: ```brew install ffmpeg``` (vía [Homebrew](https://brew.sh/))
> - Linux: ```sudo apt install ffmpeg``` (Debian/Ubuntu)

### Opcion A: Usando uv (Recomendado)

[uv](https://docs.astral.sh/uv/) descarga automaticamente Python 3.10 y crea un entorno aislado. No necesitas instalar Python o Anaconda manualmente.

1. Clona el repositorio

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Configuracion con un solo comando (instala uv + Python 3.10 + todas las dependencias)

```bash
python setup_env.py
```

3. Inicia la aplicacion

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

O haz doble clic en `OneKeyStart_uv.bat` en Windows.

### Opcion B: Usando Conda

> ⚠️ **No recomendado.** Este método no se mantendrá en el futuro. Por favor usa uv (Opción A) arriba.

<details>
<summary>Haz clic para expandir los pasos de instalacion con Conda</summary>

1. Clona el repositorio

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Instala las dependencias (requiere `python=3.10`)

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. Inicia la aplicacion

```bash
streamlit run st.py
```

</details>

### Docker
Alternativamente, puedes usar Docker (requiere CUDA 12.4 y versión del controlador NVIDIA >550), consulta la [documentación de Docker](/docs/pages/docs/docker.en-US.md):

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## APIs
AI Multilingual Video Translator admite formato de API similar a OpenAI y varias interfaces TTS:
- LLM: `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ... (ordenados por calidad; para opciones económicas prueba `gemini-3-flash` o `gpt-5.4-mini`)
- WhisperX: Ejecuta whisperX localmente o usa la API de 302.ai
- TTS: `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(¡Puedes modificar tu propio TTS en custom_tts.py!)

> **Nota:** AI Multilingual Video Translator funciona con **[302.ai](https://302.ai)** - una clave API para todos los servicios (LLM, WhisperX, TTS). ¡O ejecútalo localmente con Ollama y Edge-TTS gratis, sin necesidad de API!

Para instrucciones detalladas de instalación, configuración de API y modo por lotes, consulta la documentación: [English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
