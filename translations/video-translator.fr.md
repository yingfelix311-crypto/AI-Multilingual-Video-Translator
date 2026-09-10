# video translator

Transcrivez des vidéos, traduisez les sous-titres et produisez des versions doublées dans un même espace de travail.

[English](/README.md) · [简体中文](/translations/video-translator.zh.md) · [繁體中文](/translations/video-translator.zh-TW.md) · [日本語](/translations/video-translator.ja.md) · [Español](/translations/video-translator.es.md) · [Français](/translations/video-translator.fr.md) · [Русский](/translations/video-translator.ru.md)

---

## Choisir le point de départ

| Entrée | Préparation | Résultat |
| --- | --- | --- |
| Vidéo | Transcription, segmentation et traduction avec horodatage. | Sous-titres et tâches de doublage |
| Vidéo + SRT traduit | Importation, séparation des voix et vérification des temps et des locuteurs. | Chronologie prête |
| Chronologie prête | Synthèse vocale, assemblage audio, mixage et exportation. | Vidéo doublée |

## Démarrage local

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

Ouvrez http://127.0.0.1:8501 après le démarrage. Sous Windows, OneKeyStart.bat est également disponible.

<details>
<summary>Prérequis et configuration GPU</summary>

Python 3.10 · Git · FFmpeg

> **Note :** Pour les utilisateurs Windows avec un GPU NVIDIA, suivez ces étapes avant l'installation :
> 1. Installez [CUDA Toolkit 12.6](https://developer.download.nvidia.com/compute/cuda/12.6.0/local_installers/cuda_12.6.0_560.76_windows.exe)
> 2. Installez [CUDNN 9.3.0](https://developer.download.nvidia.com/compute/cudnn/9.3.0/local_installers/cudnn_9.3.0_windows.exe)
> 3. Ajoutez `C:\Program Files\NVIDIA\CUDNN\v9.3\bin\12.6` à votre PATH système
> 4. Redémarrez votre ordinateur

> **Note :** FFmpeg est requis. Veuillez l'installer via les gestionnaires de paquets :
> - Windows : ```choco install ffmpeg``` (via [Chocolatey](https://chocolatey.org/))
> - macOS : ```brew install ffmpeg``` (via [Homebrew](https://brew.sh/))
> - Linux : ```sudo apt install ffmpeg``` (Debian/Ubuntu)

</details>

## Configurer les services

| Étape | Intégration |
| --- | --- |
| Transcription et alignement | Qwen / DashScope ; autres moteurs ASR configurés dans config.yaml. |
| Traduction | Endpoint compatible OpenAI, nom du modèle et clé API. |
| Doublage | NoizAI, ElevenLabs, Qwen, Azure, OpenAI, GPT-SoVITS et autres moteurs TTS configurés. |

Les langues et le clonage vocal dépendent des services sélectionnés.

## Guide des fichiers

| Fichier | Rôle |
| --- | --- |
| [run_webui.py](/run_webui.py) | Lanceur de l’interface web |
| [config.yaml](/config.yaml) | Paramètres de traitement et sous-titres |
| [custom_terms.xlsx](/custom_terms.xlsx) | Terminologie personnalisée |
| [core/](/core/) | Traitement du texte et de l’audio |
| [webui/](/webui/) | Interface web et gestion des tâches |
| [video_translator_colab.ipynb](/video_translator_colab.ipynb) | Notebook Colab |

<details>
<summary>Installation et configuration API</summary>

[English](/docs/pages/docs/start.en-US.md) · [中文](/docs/pages/docs/start.zh-CN.md)

[Docker · English](/docs/pages/docs/docker.en-US.md) · [Docker · 中文](/docs/pages/docs/docker.zh-CN.md)

[Batch · English](/batch/README.md) · [Batch · 中文](/batch/README.zh.md)

</details>
