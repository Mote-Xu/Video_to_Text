"""Scene description using DeepSeek / OpenAI-compatible Vision API."""

import base64
import json
import subprocess
import time
from pathlib import Path

from models import KeyFrame, SceneDescription


def _get_windows_proxy() -> str | None:
    """Read Windows system proxy from registry. Returns None if not set."""
    try:
        result = subprocess.run(
            ["reg", "query",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
             "/v", "ProxyServer"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "ProxyServer" in line:
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        return parts[-1].strip()
    except Exception:
        pass
    return None


# Default fallback prompt — should be overridden via content_analyzer
DEFAULT_SCENE_PROMPT = """You are analyzing frames from a video. Describe what you see objectively and concisely.

Return ONLY valid JSON (no markdown):
{
  "summary": "Describe the scene: what is shown, the visual style, the main subject.",
  "objects": ["key visible elements"],
  "actions": ["what is happening in this frame"],
  "setting": "indoor/outdoor, screen recording, animation, or other",
  "on_screen_text": "any visible text, subtitles, labels, UI elements"
}"""

# Provider configs: {name: (base_url, env_var_hint)}
PROVIDERS = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_var": "DASHSCOPE_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var": "GEMINI_API_KEY",
    },
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
    scene_prompt: str | None = None,
) -> list[SceneDescription]:
    """
    Send keyframes to a vision model for scene description.

    Supports DeepSeek (default), Anthropic Claude, OpenAI-compatible APIs,
    and DashScope (通义千问 VL).

    Parameters
    ----------
    keyframes : List of keyframes to describe.
    api_key : API key for the selected provider.
    provider : "dashscope", "anthropic", "gemini", "deepseek", or "openai".
    model : Model ID (e.g. "qwen-vl-max", "deepseek-chat", "gpt-4o").
    max_tokens : Max tokens per frame response.
    temperature : Response creativity (0 = deterministic).
    scene_prompt : Custom prompt for scene description. Uses default if None.

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

    prompt = scene_prompt or DEFAULT_SCENE_PROMPT

    if provider == "anthropic":
        return _describe_with_anthropic(keyframes, api_key, model, max_tokens, temperature, prompt)
    else:
        base_url = PROVIDERS[provider]["base_url"]
        return _describe_with_openai_compat(keyframes, api_key, base_url, model, max_tokens, temperature, prompt)


def _describe_with_openai_compat(
    keyframes: list[KeyFrame],
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    scene_prompt: str,
) -> list[SceneDescription]:
    """Describe frames via OpenAI-compatible API (DeepSeek, OpenAI, etc.)."""
    from openai import OpenAI
    import httpx

    # Auto-detect Windows proxy (e.g. 127.0.0.1:24072)
    proxy_url = _get_windows_proxy()
    http_client = None
    if proxy_url:
        http_client = httpx.Client(proxy=f"http://{proxy_url}", timeout=120)

    client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)
    results: list[SceneDescription] = []

    # Gemini free tier: 5 RPM → 30s between requests (2 RPM = safe margin)
    delay = 30.0 if "generativelanguage" in base_url else 0.0

    total = len(keyframes)
    for kf in keyframes:
        if not kf.image_path.exists():
            continue

        print(f"  [{len(results)}/{total}] t={kf.timestamp_sec:.0f}s...", end=" ", flush=True)

        # Read and resize image (smaller = faster, fewer rate limits)
        from PIL import Image
        import io
        img = Image.open(kf.image_path).convert("RGB")
        img.thumbnail((512, 512), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        image_data = base64.b64encode(buf.getvalue()).decode("utf-8")

        ext = kf.image_path.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")

        data_uri = f"data:{mime};base64,{image_data}"

        raw_text = None
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": scene_prompt},
                        ],
                    }],
                )
                raw_text = response.choices[0].message.content
                break
            except Exception as e:
                err_str = str(e)
                if any(x in err_str.lower() for x in ["429", "503", "quota", "resource_exhausted", "unavailable"]):
                    wait = (attempt + 1) * 30.0
                    print(f"  Frame {kf.index} rate-limited, waiting {wait:.0f}s...")
                    time.sleep(wait)
                else:
                    print(f"  Frame {kf.index} error: {e}")
                    break  # non-retryable, skip this frame

        if raw_text is None:
            print(f"  Frame {kf.index} skipped — all retries exhausted")
            if delay > 0:
                time.sleep(delay)
            continue  # skip this frame, keep going

        print("OK")
        if delay > 0:
            time.sleep(delay)

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
    scene_prompt: str,
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
                        {"type": "text", "text": scene_prompt},
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
    """Extract JSON from model response, handling truncation gracefully."""
    text = text.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: find balanced { ... } pair (handles truncation)
    depth = 0
    json_start = text.find("{")
    if json_start != -1:
        for i in range(json_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[json_start:i + 1])
                    except json.JSONDecodeError:
                        break

    # Strategy 3: strip markdown code fences and retry
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if start != -1 and end != -1 and end > start + 3:
            inner = text[start + 3:end].strip()
            nl = inner.find("\n")
            if nl != -1 and nl < 20:
                inner = inner[nl + 1:].strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

    # Strategy 4: manually extract summary from truncated JSON
    import re
    summary_match = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    summary = summary_match.group(1) if summary_match else text[:300]
    # Fix escaped chars
    summary = summary.replace('\\"', '"').replace('\\n', ' ')

    text_match = re.search(r'"on_screen_text"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    on_screen = text_match.group(1) if text_match else ""
    on_screen = on_screen.replace('\\"', '"')

    return {
        "summary": summary,
        "objects": [],
        "actions": [],
        "setting": "",
        "on_screen_text": on_screen,
    }
