"""
Gemini image generation helper for Nano Banana / Nano Banana Pro.

Uses the REST API directly so the app does not need an additional SDK
dependency. The API key is expected in GEMINI_API_KEY.
"""
import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib import error, request


DEFAULT_MODEL = "gemini-3-pro-image-preview"
DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class GeminiImageResult:
    """Generated image bytes and metadata."""

    image_bytes: bytes
    mime_type: str
    text: str = ""


class GeminiImageGenerationError(RuntimeError):
    """Raised when Gemini image generation fails."""


def build_expression_sheet_prompt() -> str:
    """Prompt for a 2x2 PNGTuber expression sheet with fixed panel order."""
    return """Create a 2x2 PNGTuber expression sheet from the provided character image.

Output requirements:
- Output a single 2x2 grid image.
- Preserve the original character design, art style, face angle, head tilt, colors, line weight, lighting, background, and overall composition.
- Keep the character in the exact same position and scale in all four panels.
- Only change eyelids/eyes and mouth. Do not change hair, clothes, face outline, body pose, background, or camera framing.
- The final sheet must be 4:3 aspect ratio because each panel will be 640x480.

Fixed panel order:
- Top-left: eyes closed, mouth closed.
- Top-right: eyes open, mouth closed.
- Bottom-left: eyes closed, mouth open as if speaking.
- Bottom-right: eyes open, mouth open as if speaking.

Make the expression differences clean and easy to mask for PNGTuber use."""


def build_counterpart_prompt(base_eye_on: bool = True, base_mouth_on: bool = False) -> str:
    """Prompt for the second image used by the two-image workflow."""
    source_eye = "open eyes" if base_eye_on else "closed eyes"
    target_eye = "gently closed relaxed eyelids" if base_eye_on else "natural relaxed open eyes"
    source_mouth = "closed mouth" if not base_mouth_on else "open speaking mouth"
    target_mouth = "a natural open speaking mouth" if not base_mouth_on else "a closed neutral mouth"

    return f"""Edit the provided Stack-chan / PNGTuber character image.

Output a single image, not a grid.

Keep completely unchanged:
- character identity and art style
- face angle, head tilt, face outline, hair, body, clothes, background
- camera framing, position, scale, lighting, colors, and line weight

Only change these parts:
- eyes: change {source_eye} to {target_eye}
- mouth: change {source_mouth} to {target_mouth}

The result must keep the exact same composition as the input image. Make the changed eye and mouth regions clean and easy to mask for Stack-chan display assets."""


def build_emotion_prompt(emotion: str, emotion_label: Optional[str] = None) -> str:
    """Prompt for generating an emotion base image from neutral."""
    descriptions = {
        "neutral": "a calm neutral expression",
        "happy": "a clearly happy expression with gentle cheerful eyes and a friendly smile",
        "sad": "a sad expression with slightly lowered brows and a subdued mouth",
        "angry": "an angry expression with sharper eyes, lowered brows, and a displeased mouth",
        "thinking": "a thinking expression with a thoughtful gaze, slightly raised or tilted brows, and a small contemplative mouth",
    }
    target = (emotion_label or emotion).strip()
    description = descriptions.get(emotion)
    if description is None:
        description = f"a custom expression that clearly conveys this user-provided emotion label or instruction: {target}"

    return f"""Edit the provided Stack-chan / PNGTuber character image.

Output a single image, not a grid.

Create the emotion base image for: {target}.
Expression target: {description}.

Keep completely unchanged:
- character identity and art style
- face angle, head tilt, face outline, hair, body, clothes, background
- camera framing, position, scale, lighting, colors, and line weight

Only change the face expression, primarily eyebrows, eyes, eyelids, and mouth. Keep the expression suitable for small 320x240 Stack-chan display assets.

The result must keep the exact same composition as the input image."""


def generate_expression_sheet(
    api_key: str,
    image_path: str,
    prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    image_size: str = "2K",
    timeout: int = 180,
) -> GeminiImageResult:
    """Generate a 2x2 expression sheet using Gemini image generation."""
    if not api_key:
        raise GeminiImageGenerationError("GEMINI_API_KEY が設定されていません")

    source_path = Path(image_path)
    if not source_path.exists():
        raise GeminiImageGenerationError(f"画像ファイルが見つかりません: {image_path}")

    mime_type = mimetypes.guess_type(source_path.name)[0] or "image/png"
    image_b64 = base64.b64encode(source_path.read_bytes()).decode("ascii")
    prompt_text = prompt or build_expression_sheet_prompt()

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": "4:3",
                "imageSize": image_size,
            },
        },
    }

    url = DEFAULT_ENDPOINT.format(model=model)
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read()
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise GeminiImageGenerationError(f"Gemini API エラー: HTTP {e.code}\n{detail}") from e
    except error.URLError as e:
        raise GeminiImageGenerationError(f"Gemini API に接続できません: {e}") from e

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise GeminiImageGenerationError("Gemini API のレスポンス解析に失敗しました") from e

    texts = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
                continue

            inline_data = part.get("inline_data") or part.get("inlineData")
            if inline_data:
                image_data = inline_data.get("data")
                output_mime = inline_data.get("mime_type") or inline_data.get("mimeType") or "image/png"
                if image_data:
                    return GeminiImageResult(
                        image_bytes=base64.b64decode(image_data),
                        mime_type=output_mime,
                        text="\n".join(texts),
                    )

    message = data.get("error", {}).get("message") or "\n".join(texts) or "画像が返されませんでした"
    raise GeminiImageGenerationError(message)


def generate_counterpart_image(
    api_key: str,
    image_path: str,
    prompt: Optional[str] = None,
    base_eye_on: bool = True,
    base_mouth_on: bool = False,
    model: str = DEFAULT_MODEL,
    image_size: str = "1K",
    timeout: int = 180,
) -> GeminiImageResult:
    """Generate one counterpart image for the two-image workflow."""
    return generate_expression_sheet(
        api_key=api_key,
        image_path=image_path,
        prompt=prompt or build_counterpart_prompt(base_eye_on, base_mouth_on),
        model=model,
        image_size=image_size,
        timeout=timeout,
    )


def generate_emotion_image(
    api_key: str,
    image_path: str,
    emotion: str,
    prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    image_size: str = "1K",
    timeout: int = 180,
) -> GeminiImageResult:
    """Generate an emotion base image from a neutral/base image."""
    return generate_expression_sheet(
        api_key=api_key,
        image_path=image_path,
        prompt=prompt or build_emotion_prompt(emotion),
        model=model,
        image_size=image_size,
        timeout=timeout,
    )
