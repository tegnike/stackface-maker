#!/usr/bin/env python3
"""Local web app for Stack-chan face asset generation."""
from __future__ import annotations

import os
from urllib.parse import quote
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gemini_generator import DEFAULT_MODEL
from openai_generator import DEFAULT_OPENAI_IMAGE_MODEL
from web_image_service import WebImageService


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "web_static"

app = FastAPI(title="StackFace Maker")
service = WebImageService()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class GenerateEmotionRequest(BaseModel):
    sessionId: str
    emotion: str
    emotionLabel: str
    apiKey: str = ""
    model: str = DEFAULT_MODEL
    imageSize: str = "2K"
    colorMatch: bool = True
    extraPrompt: str = ""


class GenerateVariantRequest(BaseModel):
    sessionId: str
    provider: str = "gemini"
    apiKey: str = ""
    model: str = DEFAULT_MODEL
    imageSize: str = "2K"
    baseEyeOn: bool = True
    baseMouthOn: bool = True
    extraPrompt: str = ""


class PrepareRequest(BaseModel):
    sessionId: str
    baseEyeOn: bool = True
    baseMouthOn: bool = True
    colorMatch: bool = True
    feather: int = 10


class RenderRequest(BaseModel):
    sessionId: str
    eyeMask: str
    mouthMask: str
    feather: int = 10
    baseEyeOn: bool = True
    baseMouthOn: bool = True


class UseStandardRequest(BaseModel):
    sessionId: str


def json_error(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/session")
def create_session():
    session = service.create_session()
    return {"sessionId": session.id}


@app.post("/api/upload/{role}")
async def upload_image(
    role: str,
    sessionId: str = Form(...),
    emotionLabel: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    if role not in {"standard", "base", "variant"}:
        raise json_error("role must be standard, base, or variant")
    try:
        session = service.get_session(sessionId)
        path = service.save_upload(session, role, file.filename or f"{role}.png", await file.read())
        if role == "base" and emotionLabel:
            session.emotion_label = emotionLabel
        return {"url": service.image_url(session, path), "filename": path.name}
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.post("/api/generate-emotion")
def generate_emotion(req: GenerateEmotionRequest):
    try:
        session = service.get_session(req.sessionId)
        api_key = req.apiKey.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Gemini APIキーが必要です")
        path = service.generate_emotion_base(
            session=session,
            api_key=api_key,
            emotion=req.emotion,
            emotion_label=req.emotionLabel,
            model=req.model or DEFAULT_MODEL,
            image_size=req.imageSize,
            color_match=req.colorMatch,
            extra_prompt=req.extraPrompt,
        )
        return {"url": service.image_url(session, path), "filename": path.name}
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.post("/api/use-standard")
def use_standard(req: UseStandardRequest):
    try:
        session = service.get_session(req.sessionId)
        if session.standard_path is None:
            raise RuntimeError("先に標準表情の画像を選択してください")
        session.base_path = session.standard_path
        session.variant_path = None
        session.aligned_variant_path = None
        session.output_paths = []
        session.emotion_label = "標準"
        return {"url": service.image_url(session, session.standard_path), "filename": session.standard_path.name}
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.post("/api/generate-variant")
def generate_variant(req: GenerateVariantRequest):
    try:
        session = service.get_session(req.sessionId)
        provider = req.provider
        env_name = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
        api_key = req.apiKey.strip() or os.environ.get(env_name, "").strip()
        if not api_key:
            raise RuntimeError(f"{env_name} が必要です")
        default_model = DEFAULT_OPENAI_IMAGE_MODEL if provider == "openai" else DEFAULT_MODEL
        path = service.generate_opposite(
            session=session,
            provider=provider,
            api_key=api_key,
            model=req.model or default_model,
            image_size=req.imageSize,
            base_eye_on=req.baseEyeOn,
            base_mouth_on=req.baseMouthOn,
            extra_prompt=req.extraPrompt,
        )
        return {"url": service.image_url(session, path), "filename": path.name}
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.post("/api/prepare")
def prepare(req: PrepareRequest):
    try:
        session = service.get_session(req.sessionId)
        return service.prepare_pair(
            session=session,
            base_eye_on=req.baseEyeOn,
            base_mouth_on=req.baseMouthOn,
            color_match=req.colorMatch,
            feather=req.feather,
        )
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.post("/api/render")
def render(req: RenderRequest):
    try:
        session = service.get_session(req.sessionId)
        paths = service.render_from_data_urls(
            session=session,
            eye_mask_data=req.eyeMask,
            mouth_mask_data=req.mouthMask,
            feather=req.feather,
            base_eye_on=req.baseEyeOn,
            base_mouth_on=req.baseMouthOn,
        )
        return {"patterns": [service.image_url(session, p) for p in paths]}
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.get("/api/export")
def export_zip(sessionId: str, resizeCores3: bool = True):
    try:
        session = service.get_session(sessionId)
        data = service.build_export_zip(session, resize_cores3=resizeCores3)
        filename = service.safe_path_name(f"{session.emotion_label}_{session.source_name}.zip")
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="stackchan_faces.zip"; '
                    f"filename*=UTF-8''{quote(filename)}"
                )
            },
        )
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    except Exception as e:
        raise json_error(str(e))


@app.get("/api/image/{session_id}/{filename}")
def get_image(session_id: str, filename: str):
    try:
        session = service.get_session(session_id)
    except KeyError:
        raise json_error("セッションが見つかりません", 404)
    safe_name = Path(filename).name
    path = session.root / safe_name
    if not path.exists():
        raise json_error("画像が見つかりません", 404)
    return FileResponse(str(path))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web_app:app", host="127.0.0.1", port=8765, reload=False)
