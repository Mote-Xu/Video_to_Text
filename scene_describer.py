"""Scene description using DeepSeek / OpenAI-compatible Vision API."""

import base64
import json
from pathlib import Path

from models import KeyFrame, SceneDescription


SCENE_PROMPT = """Describe this video frame concisely. Return ONLY valid JSON (no markdown, no code block):

{
  "summary": "1-2 sentence description of what is happening in the frame",
  "objects": ["visible object 1", "visible object 2"],
  "actions": ["action or activity visible"],
  "setting": "indoor/outdoor and location type",
  "on_screen_text": "any visible text in the frame (or empty string if none)"
}"""

# Provider configs: {name: (base_url, env_var_hint)}
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env_var": "DEEPSEEK_API_KEY",
    },
    "anthropic": {
        "base_url": None,  # uses Anthropic SDK, not OpenAI-compatible
        "env_var": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_var": "OPENAI_API_KEY",
    },
}


class VisionError(Exception):
    """Raised when scene description fails."""


def describe_scenes(
    keyframes: list[KeyFrame],
    api_key: str,
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    max_tokens: int = 200,
    temperature: float = 0.3,
) -> list[SceneDescription]:
    """
    Send keyframes to a vision model for scene description.

    Supports DeepSeek (default), Anthropic Claude, and OpenAI-compatible APIs.

    Parameters
    ----------
    keyframes : List of keyframes to describe.
    api_key : API key for the selected provider.
    provider : "deepseek", "anthropic", or "openai".
    model : Model ID (e.g. "deepseek-chat", "gpt-4o").
    max_tokens : Max tokens per frame response.
    temperature : Response creativity (0 = deterministic).

    Returns
    -------
    List of SceneDescription objects.
    """
    if not keyframes:
        return []

    if not api_key and provider != "anthropic":
        env_var = PROVIDERS.get(provider, {}).get("env_var", "API_KEY")
        raise VisionError(
            f"{env_var} not set. Add it to .env or environment."
        )

    if provider == "anthropic":
        return _describe_with_anthropic(keyframes, api_key, model, max_tokens, temperature)
    else:
        base_url = PROVIDERS[provider]["base_url"]
        return _describe_with_openai_compat(keyframes, api_key, base_url, model, max_tokens, temperature)


def _describe_with_openai_compat(
    keyframes: list[KeyFrame],
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
) -> list[SceneDescription]:
    """Describe frames via OpenAI-compatible API (DeepSeek, OpenAI, etc.)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    results: list[SceneDescription] = []

    for kf in keyframes:
        if not kf.image_path.exists():
            continue

        # Read and encode image
        with open(kf.image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = kf.image_path.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")

        data_uri = f"data:{mime};base64,{image_data}"

        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": SCENE_PROMPT},
                    ],
                }],
            )
        except Exception as e:
            raise VisionError(f"API call failed for frame {kf.index}: {e}")

        raw_text = response.choices[0].message.content
        try:
            parsed = _parse_json_response(raw_text)
        except json.JSONDecodeError:
            parsed = {
                "summary": raw_text[:200] if raw_text else "",
                "objects": [],
                "actions": [],
                "setting": "",
                "on_screen_text": "",
            }

        results.append(SceneDescription(
            frame_index=kf.index,
            timestamp_sec=kf.timestamp_sec,
            summary=parsed.get("summary", ""),
            objects=parsed.get("objects", []),
            actions=parsed.get("actions", []),
            setting=parsed.get("setting", ""),
            on_screen_text=parsed.get("on_screen_text", ""),
        ))

    return results


def _describe_with_anthropic(
    keyframes: list[KeyFrame],
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
) -> list[SceneDescription]:
    """Describe frames via Anthropic Claude API (native SDK)."""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    results: list[SceneDescription] = []

    for kf in keyframes:
        if not kf.image_path.exists():
            continue

        with open(kf.image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        ext = kf.image_path.suffix.lower()
        media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")

        try:
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": SCENE_PROMPT},
                    ],
                }],
            )
        except Exception as e:
            raise VisionError(f"Claude API call failed for frame {kf.index}: {e}")

        raw_text = message.content[0].text
        try:
            parsed = _parse_json_response(raw_text)
        except json.JSONDecodeError:
            parsed = {
                "summary": raw_text[:200],
                "objects": [],
                "actions": [],
                "setting": "",
                "on_screen_text": "",
            }

        results.append(SceneDescription(
            frame_index=kf.index,
            timestamp_sec=kf.timestamp_sec,
            summary=parsed.get("summary", ""),
            objects=parsed.get("objects", []),
            actions=parsed.get("actions", []),
            setting=parsed.get("setting", ""),
            on_screen_text=parsed.get("on_screen_text", ""),
        ))

    return results


def _parse_json_response(text: str) -> dict:
    """Extract JSON object from the model's response, handling markdown wrapping."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)
