from pathlib import Path
from ruamel.yaml import YAML
import threading

CONFIG_PATH = 'config.yaml'
lock = threading.Lock()

yaml = YAML()
yaml.preserve_quotes = True

_PLACEHOLDER_KEYS = {
    "",
    "YOUR_API_KEY",
    "YOUR_302_API_KEY",
    "YOUR_SF_KEY",
    "your_302_api_key",
    "your_elevenlabs_api_key",
    "your_noiz_api_key",
}

# -----------------------
# load & update config
# -----------------------

def load_key(key):
    with lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

    keys = key.split('.')
    value = data
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            raise KeyError(f"Key '{k}' not found in configuration")
    return value


def load_secret(key, key_file=None):
    """Load a secret from config, falling back to a local key file if needed."""
    value = load_key(key)
    if isinstance(value, str) and value.strip() not in _PLACEHOLDER_KEYS:
        return value.strip()
    if key_file:
        path = Path(key_file)
        if path.is_file():
            file_value = path.read_text(encoding="utf-8").strip()
            if file_value:
                return file_value
    return value

def update_key(key, new_value):
    with lock:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as file:
            data = yaml.load(file)

        keys = key.split('.')
        current = data
        for k in keys[:-1]:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False

        if isinstance(current, dict) and keys[-1] in current:
            current[keys[-1]] = new_value
            with open(CONFIG_PATH, 'w', encoding='utf-8') as file:
                yaml.dump(data, file)
            return True
        else:
            raise KeyError(f"Key '{keys[-1]}' not found in configuration")
        
# basic utils
def get_joiner(language):
    if language in load_key('language_split_with_space'):
        return " "
    elif language in load_key('language_split_without_space'):
        return ""
    else:
        raise ValueError(f"Unsupported language code: {language}")

if __name__ == "__main__":
    print(load_key('language_split_with_space'))
