"""One-time migration script: extract voice_options from tts_interfaces.json into tts_voices.json."""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TTS_INTERFACES_FILE = os.path.join(SCRIPT_DIR, "tts_interfaces.json")
TTS_VOICES_FILE = os.path.join(SCRIPT_DIR, "tts_voices.json")


def migrate():
    with open(TTS_INTERFACES_FILE, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    voices_data = {"version": 1, "voices": {}}
    summary = []

    for iface in data.get("interfaces", []):
        iface_id = iface["id"]
        iface_name = iface.get("name", "")
        config = iface.get("config", {})
        voice_options = config.pop("voice_options", None)

        # Use "mimoTTS" as key for the mimoTTS interface instead of its id "8dc074bb"
        voice_key = "mimoTTS" if iface_name == "mimoTTS" else iface_id

        if voice_options:
            voice_list = [
                {
                    "voice_id": v,
                    "voice_name": "",
                    "description": "",
                    "gender": "",
                    "age": "",
                    "language": "",
                }
                for v in voice_options
            ]
            voices_data["voices"][voice_key] = voice_list
            summary.append(f"  [{voice_key}] {iface_name}: migrated {len(voice_options)} voices")
        else:
            voices_data["voices"][voice_key] = []
            summary.append(f"  [{voice_key}] {iface_name}: no voice_options, created empty list")

    # Save tts_voices.json
    with open(TTS_VOICES_FILE, "w", encoding="utf-8") as f:
        json.dump(voices_data, f, ensure_ascii=False, indent=2)

    # Save modified tts_interfaces.json (without voice_options)
    with open(TTS_INTERFACES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Migration complete!")
    print(f"  Read:  {TTS_INTERFACES_FILE}")
    print(f"  Write: {TTS_VOICES_FILE}")
    print(f"  Updated: {TTS_INTERFACES_FILE} (voice_options removed)")
    print()
    print("Summary:")
    for line in summary:
        print(line)
    print()
    print(f"Total interfaces processed: {len(summary)}")
    total_voices = sum(len(v) for v in voices_data["voices"].values())
    print(f"Total voices migrated: {total_voices}")


if __name__ == "__main__":
    migrate()
