<div align="center">

# AI Multilingual Video Translator

[**English**](/README.md)｜[**简体中文**](/translations/README.zh.md)｜[**繁體中文**](/translations/README.zh-TW.md)｜[**日本語**](/translations/README.ja.md)｜[**Español**](/translations/README.es.md)｜[**Русский**](/translations/README.ru.md)｜[**Français**](/translations/README.fr.md)

</div>

## 🌟 Aperçu

AI Multilingual Video Translator est un outil tout-en-un de traduction, de localisation et de doublage vidéo visant à générer des sous-titres de qualité Netflix. Il élimine les traductions automatiques rigides et les sous-titres multi-lignes tout en ajoutant un doublage de haute qualité, permettant le partage des connaissances à l'échelle mondiale au-delà des barrières linguistiques.

Fonctionnalités principales :
- 🎥 Téléchargement de vidéos YouTube via yt-dlp

- **🎙️ Reconnaissance de sous-titres au niveau des mots et à faible illusion avec WhisperX**

- **📝 Segmentation des sous-titres basée sur le NLP et l'IA**

- **📚 Terminologie personnalisée + générée par IA pour une traduction cohérente**

- **🔄 Processus en 3 étapes : Traduction-Réflexion-Adaptation pour une qualité cinématographique**

- **✅ Sous-titres uniquement sur une ligne, aux normes Netflix**

- **🗣️ Doublage avec GPT-SoVITS, Azure, OpenAI et plus**

- 🚀 Démarrage et traitement en un clic dans Streamlit

- 🌍 Support multi-langues dans l'interface utilisateur Streamlit

- 📝 Journalisation détaillée avec reprise de la progression

- 🔍 Sélecteur de modèles avec recherche — récupère automatiquement la liste complète des modèles depuis votre API

- ⏯️ Contrôle des tâches — mettez en pause, reprenez ou arrêtez le traitement à n'importe quelle étape

Différence par rapport aux projets similaires : **Sous-titres sur une seule ligne uniquement, qualité de traduction supérieure, expérience de doublage transparente**

### Support des langues

**Support des langues d'entrée (d'autres à venir) :**

🇺🇸 Anglais 🤩 | 🇷🇺 Russe 😊 | 🇫🇷 Français 🤩 | 🇩🇪 Allemand 🤩 | 🇮🇹 Italien 🤩 | 🇪🇸 Espagnol 🤩 | 🇯🇵 Japonais 😐 | 🇨🇳 Chinois* 😊

> *Le chinois utilise un modèle whisper séparé amélioré par la ponctuation, pour l'instant...

**La traduction prend en charge toutes les langues, tandis que la langue de doublage dépend de la méthode TTS choisie.**

## Installation

> **Note :** Pour les utilisateurs Windows avec un GPU NVIDIA, suivez ces étapes avant l'installation :
> 1. Installez [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Installez [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Ajoutez `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` à votre PATH système
> 4. Redémarrez votre ordinateur

> **Note :** FFmpeg est requis. Veuillez l'installer via les gestionnaires de paquets :
> - Windows : ```choco install ffmpeg``` (via [Chocolatey](https://chocolatey.org/))
> - macOS : ```brew install ffmpeg``` (via [Homebrew](https://brew.sh/))
> - Linux : ```sudo apt install ffmpeg``` (Debian/Ubuntu)

### Option A : Utiliser uv (Recommande)

[uv](https://docs.astral.sh/uv/) telecharge automatiquement Python 3.10 et cree un environnement isole. Pas besoin d'installer Python ou Anaconda manuellement.

1. Clonez le depot

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Configuration en une commande (installe uv + Python 3.10 + toutes les dependances)

```bash
python setup_env.py
```

3. Demarrer l'application

```bash
.venv\Scripts\streamlit run st.py        # Windows
.venv/bin/streamlit run st.py            # macOS / Linux
```

Ou double-cliquez sur `OneKeyStart_uv.bat` sous Windows.

### Option B : Utiliser Conda

> ⚠️ **Non recommandé.** Cette méthode ne sera plus maintenue à l'avenir. Veuillez utiliser uv (Option A) ci-dessus.

<details>
<summary>Cliquez pour afficher les etapes d'installation avec Conda</summary>

1. Clonez le depot

```bash
git clone https://github.com/yingfelix311-crypto/AI-Multilingual-Video-Translator.git
cd AI-Multilingual-Video-Translator
```

2. Installez les dependances (necessite `python=3.10`)

```bash
conda create -n ai-video-translator python=3.10.0 -y
conda activate ai-video-translator
python install.py
```

3. Demarrer l'application

```bash
streamlit run st.py
```

</details>

### Docker
Alternativement, vous pouvez utiliser Docker (nécessite CUDA 12.4 et NVIDIA Driver version >550), voir [Documentation Docker](/docs/pages/docs/docker.en-US.md) :

```bash
docker build -t ai-video-translator .
docker run -d -p 8501:8501 --gpus all ai-video-translator
```

## APIs
AI Multilingual Video Translator prend en charge le format d'API OpenAI et diverses interfaces TTS :
- LLM : `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3.1-pro`, `deepseek-v3`, `grok-4.1`, ... (triés par qualité ; pour les options économiques essayez `gemini-3-flash` ou `gpt-5.4-mini`)
- WhisperX : Exécutez whisperX localement ou utilisez l'API 302.ai
- TTS : `azure-tts`, `openai-tts`, `siliconflow-fishtts`, **`fish-tts`**, `GPT-SoVITS`, `edge-tts`, `*custom-tts`(Vous pouvez modifier votre propre TTS dans custom_tts.py !)

> **Note :** AI Multilingual Video Translator fonctionne avec **[302.ai](https://302.ai)** - une seule clé API pour tous les services (LLM, WhisperX, TTS). Ou exécutez localement avec Ollama et Edge-TTS gratuitement, sans API nécessaire !

Pour des instructions détaillées sur l'installation, la configuration de l'API et le mode batch, veuillez consulter la documentation : [English](/docs/pages/docs/start.en-US.md) | [中文](/docs/pages/docs/start.zh-CN.md)
