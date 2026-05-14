"""
OpenAI image generation helper.

Uses the Image Edit API directly so the app does not need an SDK dependency.
The API key can be supplied from the UI or OPENAI_API_KEY.
"""
import base64
import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib import error, request


DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
OPENAI_IMAGE_EDIT_ENDPOINT = "https://api.openai.com/v1/images/edits"


@dataclass
class OpenAIImageResult:
    """Generated image bytes and metadata."""

    image_bytes: bytes
    mime_type: str = "image/png"


class OpenAIImageGenerationError(RuntimeError):
    """Raised when OpenAI image generation fails."""


def generate_counterpart_image_openai(
    api_key: str,
    image_path: str,
    prompt: str,
    model: str = DEFAULT_OPENAI_IMAGE_MODEL,
    size: str = "auto",
    quality: str = "medium",
    timeout: int = 180,
) -> OpenAIImageResult:
    """Generate one counterpart image from a source image using OpenAI Image Edit."""
    if not api_key:
        raise OpenAIImageGenerationError("OpenAI APIキーが設定されていません")

    source_path = Path(image_path)
    if not source_path.exists():
        raise OpenAIImageGenerationError(f"画像ファイルが見つかりません: {image_path}")

    fields = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    files = {
        "image": (
            source_path.name,
            source_path.read_bytes(),
            mimetypes.guess_type(source_path.name)[0] or "image/png",
        )
    }

    body, content_type = _encode_multipart(fields, files)
    req = request.Request(
        OPENAI_IMAGE_EDIT_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": content_type,
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_body = response.read()
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise OpenAIImageGenerationError(f"OpenAI API エラー: HTTP {e.code}\n{detail}") from e
    except error.URLError as e:
        raise OpenAIImageGenerationError(f"OpenAI API に接続できません: {e}") from e

    try:
        data = json.loads(response_body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise OpenAIImageGenerationError("OpenAI API のレスポンス解析に失敗しました") from e

    items = data.get("data") or []
    if not items or not items[0].get("b64_json"):
        message = data.get("error", {}).get("message") or "画像が返されませんでした"
        raise OpenAIImageGenerationError(message)

    return OpenAIImageResult(image_bytes=base64.b64decode(items[0]["b64_json"]))


def _encode_multipart(fields: dict, files: dict) -> tuple:
    """Encode multipart/form-data without adding a requests dependency."""
    boundary = f"----EasyPNGTuber{uuid.uuid4().hex}"
    chunks = []

    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])

    for name, (filename, content, mime_type) in files.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            content,
            b"\r\n",
        ])

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
