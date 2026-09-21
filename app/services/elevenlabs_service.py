import base64
import os
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
# Default ElevenLabs voice ID (Rachel)
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


def generate_speech_audio(text: str, voice_id: Optional[str] = None) -> Optional[str]:
    """
    Calls ElevenLabs Text-to-Speech API and returns base64 encoded MP3 audio.
    Returns None if ELEVENLABS_API_KEY is not configured or if the request fails.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY") or ELEVENLABS_API_KEY
    if not api_key:
        logger.warning("ELEVENLABS_API_KEY is not set. Audio response generation skipped.")
        return None

    target_voice = voice_id or DEFAULT_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{target_voice}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }

    data = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=data, headers=headers)
            if response.status_code == 200:
                audio_bytes = response.content
                return base64.b64encode(audio_bytes).decode("utf-8")
            else:
                logger.error(f"ElevenLabs API error ({response.status_code}): {response.text}")
                return None
    except Exception as e:
        logger.error(f"Failed to generate ElevenLabs speech: {e}")
        return None

