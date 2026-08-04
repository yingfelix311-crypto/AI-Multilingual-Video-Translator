import streamlit as st
import requests
from translations.translations import translate as t
from core.utils import *


def config_input(label, key, help=None, placeholder=None):
    """Generic config input handler"""
    val = st.text_input(label, value=load_key(key), help=help, placeholder=placeholder)
    if val != load_key(key):
        update_key(key, val)
    return val


def _fetch_model_list(base_url, api_key):
    """Fetch available models from OpenAI-compatible /v1/models endpoint."""
    if not api_key or not base_url:
        return []
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/models"
    try:
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return sorted([m["id"] for m in data if "id" in m])
    except Exception:
        return []


def _search_models(search_term, **kwargs):
    """Search function for st_searchbox — returns models matching the search term."""
    models = st.session_state.get("_model_list", [])
    if not search_term:
        return models if models else []
    term = search_term.lower()
    matched = [m for m in models if term in m.lower()]
    # Always include the raw input as an option so users can type custom model names
    if search_term not in matched:
        matched.insert(0, search_term)
    return matched


def page_setting():
    # Widen the sidebar slightly to accommodate the model searchbox
    st.markdown(
        """<style>[data-testid="stSidebar"] {min-width: 420px; max-width: 420px;}</style>""",
        unsafe_allow_html=True,
    )

    # with st.expander(t("Youtube Settings"), expanded=True):
    #     config_input(t("Cookies Path"), "youtube.cookies_path")

    with st.expander(t("LLM Configuration"), expanded=True):
        from core.utils.config_utils import load_secret
        api_key_resolved = load_secret("api.key", "GEMINI_API_KEY")
        api_key_display = load_key("api.key")
        if api_key_display in ("", "YOUR_API_KEY") and api_key_resolved not in ("", "YOUR_API_KEY"):
            st.caption("Using API key from GEMINI_API_KEY file")
        config_input(t("API_KEY"), "api.key", placeholder=t("Enter your API key"))
        config_input(
            t("BASE_URL"),
            "api.base_url",
            help=t("Openai format, will add /v1/chat/completions automatically"),
        )

        # Try to use searchbox for model selection, fall back to text_input
        try:
            from streamlit_searchbox import st_searchbox
            from streamlit_searchbox import _list_to_options_js, _list_to_options_py

            if st.button(
                t("Fetch Model List"), key="fetch_models", use_container_width=True
            ):
                with st.spinner(t("Fetching models...")):
                    models = _fetch_model_list(
                        load_key("api.base_url"), load_key("api.key")
                    )
                    st.session_state["_model_list"] = models
                    if models:
                        # Update searchbox internal state directly so dropdown shows options
                        sb_key = "model_searchbox"
                        if sb_key in st.session_state:
                            st.session_state[sb_key]["options_js"] = (
                                _list_to_options_js(models)
                            )
                            st.session_state[sb_key]["options_py"] = (
                                _list_to_options_py(models)
                            )
                        st.toast(
                            t("Fetched {n} models").replace("{n}", str(len(models))),
                            icon="✅",
                        )
                    else:
                        st.toast(
                            t(
                                "Failed to fetch models, please check API Key and Base URL"
                            ),
                            icon="❌",
                        )

            current_model = load_key("api.model")
            model_list = st.session_state.get("_model_list", None)

            sb_key = "model_searchbox"
            selected = st_searchbox(
                _search_models,
                placeholder=t("Search or enter model name"),
                default=current_model if current_model else None,
                default_searchterm=current_model if current_model else "",
                default_use_searchterm=True,
                default_options=model_list if model_list else None,
                key=sb_key,
                clear_on_submit=False,
            )
            if selected and selected != load_key("api.model"):
                update_key("api.model", selected)

            if st.button("📡 " + t("Check API"), key="api", use_container_width=True):
                with st.spinner(t("Check API") + "..."):
                    is_valid = check_api()
                st.toast(
                    t("API Key is valid") if is_valid else t("API Key is invalid"),
                    icon="✅" if is_valid else "❌",
                )
        except ImportError:
            c1, c2 = st.columns([4, 1])
            with c1:
                config_input(
                    t("MODEL"),
                    "api.model",
                    help=t("click to check API validity") + " 👉",
                    placeholder=t("Search or enter model name"),
                )
            with c2:
                if st.button("📡", key="api"):
                    is_valid = check_api()
                    st.toast(
                        t("API Key is valid") if is_valid else t("API Key is invalid"),
                        icon="✅" if is_valid else "❌",
                    )
        llm_support_json = st.toggle(
            t("LLM JSON Format Support"),
            value=load_key("api.llm_support_json"),
            help=t("Enable if your LLM supports JSON mode output"),
        )
        if llm_support_json != load_key("api.llm_support_json"):
            update_key("api.llm_support_json", llm_support_json)
            st.rerun()
    with st.expander(t("Subtitles Settings"), expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            langs = {
                "🇺🇸 English": "en",
                "🇨🇳 简体中文": "zh",
                "🇪🇸 Español": "es",
                "🇷🇺 Русский": "ru",
                "🇫🇷 Français": "fr",
                "🇩🇪 Deutsch": "de",
                "🇮🇹 Italiano": "it",
                "🇯🇵 日本語": "ja",
            }
            lang = st.selectbox(
                t("Recog Lang"),
                options=list(langs.keys()),
                index=list(langs.values()).index(load_key("whisper.language")),
            )
            if langs[lang] != load_key("whisper.language"):
                update_key("whisper.language", langs[lang])
                st.rerun()

        runtime = st.selectbox(
            t("WhisperX Runtime"),
            options=["local", "cloud", "elevenlabs"],
            index=["local", "cloud", "elevenlabs"].index(load_key("whisper.runtime")),
            format_func=lambda x: {
                "local": t("Local"),
                "cloud": t("Cloud"),
                "elevenlabs": t("ElevenLabs"),
            }[x],
            help=t(
                "Local runtime requires >8GB GPU, cloud runtime requires 302ai API key, elevenlabs runtime requires ElevenLabs API key"
            ),
        )
        if runtime != load_key("whisper.runtime"):
            update_key("whisper.runtime", runtime)
            st.rerun()
        if runtime == "cloud":
            config_input(t("WhisperX 302ai API"), "whisper.whisperX_302_api_key")
        if runtime == "elevenlabs":
            config_input(t("ElevenLabs API"), "whisper.elevenlabs_api_key")

        with c2:
            target_language = st.text_input(
                t("Target Lang"),
                value=load_key("target_language"),
                help=t(
                    "Input any language in natural language, as long as llm can understand"
                ),
            )
            if target_language != load_key("target_language"):
                update_key("target_language", target_language)
                st.rerun()

        demucs = st.toggle(
            t("Vocal separation enhance"),
            value=load_key("demucs"),
            help=t(
                "Recommended for videos with loud background noise, but will increase processing time"
            ),
        )
        if demucs != load_key("demucs"):
            update_key("demucs", demucs)
            st.rerun()

        from core._1_ytdlp import is_audio_only_input
        audio_only = is_audio_only_input()
        if audio_only:
            st.toggle(
                t("Burn-in Subtitles"),
                value=False,
                disabled=True,
                help=t("Audio-only input produces subtitle files only; no video is generated."),
            )
        else:
            burn_subtitles = st.toggle(
                t("Burn-in Subtitles"),
                value=load_key("burn_subtitles"),
                help=t(
                    "Whether to burn subtitles into the video, will increase processing time"
                ),
            )
            if burn_subtitles != load_key("burn_subtitles"):
                update_key("burn_subtitles", burn_subtitles)
                st.rerun()
    with st.expander(t("Dubbing Settings"), expanded=True):
        tts_methods = [
            "azure_tts",
            "openai_tts",
            "fish_tts",
            "sf_fish_tts",
            "edge_tts",
            "gpt_sovits",
            "custom_tts",
            "elevenlabs_tts",
            "sf_cosyvoice2",
            "f5tts",
        ]
        tts_method_labels = {
            "azure_tts": t("Azure TTS"),
            "openai_tts": t("OpenAI TTS"),
            "fish_tts": t("Fish TTS"),
            "sf_fish_tts": t("SiliconFlow Fish TTS"),
            "edge_tts": t("Edge TTS"),
            "gpt_sovits": t("GPT-SoVITS"),
            "custom_tts": "NoizAI TTS",
            "elevenlabs_tts": "ElevenLabs TTS",
            "sf_cosyvoice2": t("SiliconFlow CosyVoice2"),
            "f5tts": t("F5-TTS"),
        }
        select_tts = st.selectbox(
            t("TTS Method"),
            options=tts_methods,
            index=tts_methods.index(load_key("tts_method")),
            format_func=lambda x: tts_method_labels[x],
        )
        if select_tts != load_key("tts_method"):
            update_key("tts_method", select_tts)
            st.rerun()

        # sub settings for each tts method
        if select_tts == "sf_fish_tts":
            config_input(t("SiliconFlow API Key"), "sf_fish_tts.api_key")

            # Add mode selection dropdown
            mode_options = {
                "preset": t("Preset"),
                "custom": t("Refer_stable"),
                "dynamic": t("Refer_dynamic"),
            }
            selected_mode = st.selectbox(
                t("Mode Selection"),
                options=list(mode_options.keys()),
                format_func=lambda x: mode_options[x],
                index=list(mode_options.keys()).index(load_key("sf_fish_tts.mode"))
                if load_key("sf_fish_tts.mode") in mode_options.keys()
                else 0,
            )
            if selected_mode != load_key("sf_fish_tts.mode"):
                update_key("sf_fish_tts.mode", selected_mode)
                st.rerun()
            if selected_mode == "preset":
                config_input(t("Voice"), "sf_fish_tts.voice")

        elif select_tts == "openai_tts":
            config_input(t("302ai API"), "openai_tts.api_key")
            config_input(t("OpenAI Voice"), "openai_tts.voice")

        elif select_tts == "fish_tts":
            config_input(t("302ai API"), "fish_tts.api_key")
            fish_tts_character = st.selectbox(
                t("Fish TTS Character"),
                options=list(load_key("fish_tts.character_id_dict").keys()),
                index=list(load_key("fish_tts.character_id_dict").keys()).index(
                    load_key("fish_tts.character")
                ),
            )
            if fish_tts_character != load_key("fish_tts.character"):
                update_key("fish_tts.character", fish_tts_character)
                st.rerun()

        elif select_tts == "azure_tts":
            config_input(t("302ai API"), "azure_tts.api_key")
            config_input(t("Azure Voice"), "azure_tts.voice")

        elif select_tts == "gpt_sovits":
            st.info(t("Please refer to Github homepage for GPT_SoVITS configuration"))
            config_input(t("SoVITS Character"), "gpt_sovits.character")

            refer_mode_options = {
                1: t("Mode 1: Use provided reference audio only"),
                2: t("Mode 2: Use first audio from video as reference"),
                3: t("Mode 3: Use each audio from video as reference"),
            }
            selected_refer_mode = st.selectbox(
                t("Refer Mode"),
                options=list(refer_mode_options.keys()),
                format_func=lambda x: refer_mode_options[x],
                index=list(refer_mode_options.keys()).index(
                    load_key("gpt_sovits.refer_mode")
                ),
                help=t("Configure reference audio mode for GPT-SoVITS"),
            )
            if selected_refer_mode != load_key("gpt_sovits.refer_mode"):
                update_key("gpt_sovits.refer_mode", selected_refer_mode)
                st.rerun()

        elif select_tts == "edge_tts":
            config_input(t("Edge TTS Voice"), "edge_tts.voice")

        elif select_tts == "elevenlabs_tts":
            from core.utils.config_utils import load_secret
            elevenlabs_key = load_secret("elevenlabs_tts.api_key", "ELEVENLABS_API_KEY")
            if (
                load_key("elevenlabs_tts.api_key") in ("", "YOUR_API_KEY")
                and elevenlabs_key not in ("", "YOUR_API_KEY")
            ):
                st.caption("Using API key from ELEVENLABS_API_KEY file")
            config_input("ElevenLabs API Key", "elevenlabs_tts.api_key")

            mode_options = {
                "clone": "Clone exact timestamp reference",
                "preset": "Preset voice_id",
            }
            current_mode = load_key("elevenlabs_tts.mode")
            selected_mode = st.selectbox(
                "ElevenLabs Mode",
                options=list(mode_options.keys()),
                format_func=lambda x: mode_options[x],
                index=list(mode_options.keys()).index(current_mode),
            )
            if selected_mode != current_mode:
                update_key("elevenlabs_tts.mode", selected_mode)
                st.rerun()
            if selected_mode == "preset":
                config_input("ElevenLabs Voice ID", "elevenlabs_tts.voice_id")
            config_input("ElevenLabs Model ID", "elevenlabs_tts.model_id")

        elif select_tts == "custom_tts":
            from core.utils.config_utils import load_secret
            noiz_key = load_secret("noiz_tts.api_key", "NOIZ_API_KEY")
            if load_key("noiz_tts.api_key") in ("", "YOUR_API_KEY") and noiz_key not in ("", "YOUR_API_KEY"):
                st.caption("Using API key from NOIZ_API_KEY file")
            config_input("NoizAI API Key", "noiz_tts.api_key")

            mode_options = {
                "clone": "Clone from video (refers/)",
                "preset": "Preset voice_id",
            }
            current_mode = load_key("noiz_tts.mode")
            if current_mode not in mode_options:
                current_mode = "clone"
            selected_mode = st.selectbox(
                "NoizAI Mode",
                options=list(mode_options.keys()),
                format_func=lambda x: mode_options[x],
                index=list(mode_options.keys()).index(current_mode),
                help="Clone uses output/audio/refers/{n}.wav per sentence, like CosyVoice2",
            )
            if selected_mode != load_key("noiz_tts.mode"):
                update_key("noiz_tts.mode", selected_mode)
                st.rerun()

            if selected_mode == "preset":
                config_input("NoizAI Voice ID", "noiz_tts.voice_id")
            else:
                speaker_tagging = st.toggle(
                    "Merge continuous lines by speaker",
                    value=bool(load_key("speaker_tagging.enabled")),
                    help="Gemini identifies speakers and merges only high-confidence continuous utterances",
                )
                if speaker_tagging != load_key("speaker_tagging.enabled"):
                    update_key("speaker_tagging.enabled", speaker_tagging)
                    st.rerun()

                if speaker_tagging:
                    min_confidence = st.slider(
                        "Speaker merge confidence",
                        min_value=0.5,
                        max_value=1.0,
                        value=float(load_key("speaker_tagging.min_confidence")),
                        step=0.05,
                    )
                    if min_confidence != load_key("speaker_tagging.min_confidence"):
                        update_key("speaker_tagging.min_confidence", min_confidence)
                        st.rerun()

                    try:
                        current_gap = float(load_key("speaker_tagging.tts_merge_max_gap"))
                    except KeyError:
                        current_gap = float(load_key("speaker_tagging.max_gap"))
                    max_gap = st.slider(
                        "Merge-with-previous max gap (seconds)",
                        min_value=0.0,
                        max_value=3.0,
                        value=current_gap,
                        step=0.1,
                        help="Same limit for reference pooling and TTS source merge",
                    )
                    if abs(max_gap - current_gap) > 1e-9:
                        update_key("speaker_tagging.tts_merge_max_gap", max_gap)
                        st.rerun()
            config_input("NoizAI Target Lang", "noiz_tts.target_lang")
            similarity_enh = st.toggle(
                "NoizAI Similarity Enhance",
                value=bool(load_key("noiz_tts.similarity_enh")),
            )
            if similarity_enh != load_key("noiz_tts.similarity_enh"):
                update_key("noiz_tts.similarity_enh", similarity_enh)
                st.rerun()

        elif select_tts == "sf_cosyvoice2":
            config_input(t("SiliconFlow API Key"), "sf_cosyvoice2.api_key")

        elif select_tts == "f5tts":
            config_input(t("302ai API"), "f5tts.302_api")


def check_api():
    try:
        resp = ask_gpt(
            "This is a test, response 'message':'success' in json format.",
            resp_type="json",
            log_title="None",
        )
        return resp.get("message") == "success"
    except Exception:
        return False


if __name__ == "__main__":
    check_api()
