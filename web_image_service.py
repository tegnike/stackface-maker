"""Image processing service for the local Stack-chan web app."""
from __future__ import annotations

import base64
import io
import re
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from aligner import Aligner, AlignConfig
from compositor import Compositor, CompositeConfig
from cv2_utils import load_image_as_bgra, save_image
from gemini_generator import (
    DEFAULT_MODEL,
    GeminiImageGenerationError,
    build_counterpart_prompt,
    build_emotion_prompt,
    generate_counterpart_image,
    generate_emotion_image,
)
from openai_generator import (
    DEFAULT_OPENAI_IMAGE_MODEL,
    generate_counterpart_image_openai,
)


PATTERN_NAMES = [
    "eyeOFF_mouthOFF.png",
    "eyeON_mouthOFF.png",
    "eyeOFF_mouthON.png",
    "eyeON_mouthON.png",
]


@dataclass
class WebSession:
    id: str
    root: Path
    standard_path: Optional[Path] = None
    base_path: Optional[Path] = None
    variant_path: Optional[Path] = None
    aligned_variant_path: Optional[Path] = None
    output_paths: list[Path] = field(default_factory=list)
    base_eye_on: bool = True
    base_mouth_on: bool = False
    source_name: str = "output"
    emotion_label: str = "標準"


class WebImageService:
    def __init__(self, root: Optional[Path] = None):
        self.root = root or Path(tempfile.gettempdir()) / "easy_pngtuber_web"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, WebSession] = {}
        self.compositor = Compositor(CompositeConfig())
        self.aligner = Aligner(AlignConfig())

    def create_session(self) -> WebSession:
        sid = uuid.uuid4().hex
        session_root = self.root / sid
        session_root.mkdir(parents=True, exist_ok=True)
        session = WebSession(id=sid, root=session_root)
        self.sessions[sid] = session
        return session

    def get_session(self, sid: str) -> WebSession:
        if sid not in self.sessions:
            raise KeyError("session not found")
        return self.sessions[sid]

    def image_url(self, session: WebSession, path: Path) -> str:
        return f"/api/image/{session.id}/{path.name}"

    def save_upload(self, session: WebSession, role: str, filename: str, data: bytes) -> Path:
        image = self.decode_image_bytes(data)
        target = session.root / f"{role}.png"
        if not save_image(str(target), image):
            raise RuntimeError("画像の保存に失敗しました")

        if role == "standard":
            session.standard_path = target
            session.source_name = self.safe_stem(filename)
            if session.base_path is None:
                session.base_path = target
                session.emotion_label = "標準"
        elif role == "base":
            session.base_path = target
        elif role == "variant":
            session.variant_path = target
        else:
            raise ValueError("unknown role")
        return target

    def generate_emotion_base(
        self,
        session: WebSession,
        provider: str,
        api_key: str,
        emotion: str,
        emotion_label: str,
        model: str = DEFAULT_MODEL,
        image_size: str = "2K",
        color_match: bool = True,
        extra_prompt: str = "",
    ) -> Path:
        source = session.standard_path or session.base_path
        if source is None:
            raise RuntimeError("先に標準表情の画像を選択してください")

        prompt = self.append_extra_prompt(build_emotion_prompt(emotion, emotion_label), extra_prompt)
        if provider == "openai":
            result = generate_counterpart_image_openai(
                api_key=api_key,
                image_path=str(source),
                prompt=prompt,
                model=model or DEFAULT_OPENAI_IMAGE_MODEL,
            )
        else:
            result = generate_emotion_image(
                api_key=api_key,
                image_path=str(source),
                emotion=emotion,
                prompt=prompt,
                model=model,
                image_size=image_size,
            )
        generated = self.decode_image_bytes(result.image_bytes)
        reference = load_image_as_bgra(str(source))
        generated = cv2.resize(generated, (reference.shape[1], reference.shape[0]), interpolation=cv2.INTER_AREA)
        if color_match:
            generated = self.match_generated_color_to_reference(reference, generated)

        output = session.root / "base.png"
        if not save_image(str(output), generated):
            raise RuntimeError("感情画像の保存に失敗しました")
        session.base_path = output
        session.variant_path = None
        session.aligned_variant_path = None
        session.output_paths = []
        session.emotion_label = emotion_label
        return output

    def generate_opposite(
        self,
        session: WebSession,
        provider: str,
        api_key: str,
        model: str,
        image_size: str,
        base_eye_on: bool,
        base_mouth_on: bool,
        extra_prompt: str = "",
    ) -> Path:
        if session.base_path is None:
            raise RuntimeError("先に基準画像を選択してください")

        prompt = self.append_extra_prompt(build_counterpart_prompt(base_eye_on, base_mouth_on), extra_prompt)
        if provider == "openai":
            result = generate_counterpart_image_openai(
                api_key=api_key,
                image_path=str(session.base_path),
                prompt=prompt,
                model=model or DEFAULT_OPENAI_IMAGE_MODEL,
                size="auto",
            )
        else:
            result = generate_counterpart_image(
                api_key=api_key,
                image_path=str(session.base_path),
                prompt=prompt,
                base_eye_on=base_eye_on,
                base_mouth_on=base_mouth_on,
                model=model or DEFAULT_MODEL,
                image_size=image_size,
            )

        base = load_image_as_bgra(str(session.base_path))
        generated = self.decode_image_bytes(result.image_bytes)
        generated = cv2.resize(generated, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
        output = session.root / "variant.png"
        if not save_image(str(output), generated):
            raise RuntimeError("反対状態画像の保存に失敗しました")
        session.variant_path = output
        session.aligned_variant_path = None
        session.output_paths = []
        return output

    def append_extra_prompt(self, base_prompt: str, extra_prompt: str) -> str:
        extra = (extra_prompt or "").strip()
        if not extra:
            return base_prompt
        return f"{base_prompt}\n\nAdditional user instructions:\n{extra}"

    def prepare_pair(
        self,
        session: WebSession,
        base_eye_on: bool,
        base_mouth_on: bool,
        color_match: bool = True,
        feather: int = 10,
    ) -> dict:
        if session.base_path is None or session.variant_path is None:
            raise RuntimeError("基準画像と反対状態の画像を選択してください")

        base = load_image_as_bgra(str(session.base_path))
        variant = load_image_as_bgra(str(session.variant_path))
        if color_match:
            base = self.match_base_color_to_standard_if_needed(session, base)

        if variant.shape[:2] != base.shape[:2]:
            variant = cv2.resize(variant, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_LINEAR)
        aligned_variant, success, score = self.align_variant_to_base(base, variant)
        if color_match:
            aligned_variant = self.match_generated_color_to_reference(base, aligned_variant)

        aligned_path = session.root / "aligned_variant.png"
        save_image(str(aligned_path), aligned_variant)
        base_work_path = session.root / "base_work.png"
        save_image(str(base_work_path), base)
        session.base_path = base_work_path
        session.aligned_variant_path = aligned_path
        session.base_eye_on = base_eye_on
        session.base_mouth_on = base_mouth_on

        eye_mask = self.build_auto_part_mask(base, aligned_variant, "eye")
        mouth_mask = self.build_auto_part_mask(base, aligned_variant, "mouth")
        if eye_mask is None:
            eye_mask = np.zeros(base.shape[:2], dtype=np.uint8)
        if mouth_mask is None:
            mouth_mask = np.zeros(base.shape[:2], dtype=np.uint8)

        eye_mask_path = session.root / "eye_mask.png"
        mouth_mask_path = session.root / "mouth_mask.png"
        cv2.imwrite(str(eye_mask_path), eye_mask)
        cv2.imwrite(str(mouth_mask_path), mouth_mask)

        outputs = self.render_patterns(session, eye_mask, mouth_mask, feather, base_eye_on, base_mouth_on)
        return {
            "alignmentSuccess": success,
            "alignmentScore": score,
            "baseUrl": self.image_url(session, base_work_path),
            "variantUrl": self.image_url(session, aligned_path),
            "eyeMaskUrl": self.image_url(session, eye_mask_path),
            "mouthMaskUrl": self.image_url(session, mouth_mask_path),
            "patterns": [self.image_url(session, p) for p in outputs],
        }

    def render_from_data_urls(
        self,
        session: WebSession,
        eye_mask_data: str,
        mouth_mask_data: str,
        feather: int,
        base_eye_on: bool,
        base_mouth_on: bool,
    ) -> list[Path]:
        eye_mask = self.decode_mask_data_url(eye_mask_data)
        mouth_mask = self.decode_mask_data_url(mouth_mask_data)
        return self.render_patterns(session, eye_mask, mouth_mask, feather, base_eye_on, base_mouth_on)

    def render_patterns(
        self,
        session: WebSession,
        eye_mask: np.ndarray,
        mouth_mask: np.ndarray,
        feather: int,
        base_eye_on: bool,
        base_mouth_on: bool,
    ) -> list[Path]:
        if session.base_path is None or session.aligned_variant_path is None:
            raise RuntimeError("先に4パターンを作成してください")
        base = load_image_as_bgra(str(session.base_path))
        variant = load_image_as_bgra(str(session.aligned_variant_path))
        if eye_mask.shape != base.shape[:2]:
            eye_mask = cv2.resize(eye_mask, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_NEAREST)
        if mouth_mask.shape != base.shape[:2]:
            mouth_mask = cv2.resize(mouth_mask, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_NEAREST)

        patterns = self.generate_4_patterns_from_pair(
            base,
            variant,
            eye_mask,
            variant,
            mouth_mask,
            feather,
            base_eye_on,
            base_mouth_on,
        )
        output_paths = []
        for name, image in zip(PATTERN_NAMES, patterns):
            path = session.root / name
            save_image(str(path), image)
            output_paths.append(path)
        session.output_paths = output_paths
        return output_paths

    def build_export_zip(self, session: WebSession, resize_cores3: bool = True) -> bytes:
        if len(session.output_paths) != 4:
            raise RuntimeError("保存する4パターンがありません")

        folder = self.safe_path_name(f"{session.emotion_label}_{session.source_name}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in session.output_paths:
                image = load_image_as_bgra(str(path))
                if resize_cores3:
                    image = self.prepare_output_image(image)
                ok, encoded = cv2.imencode(".png", image)
                if not ok:
                    raise RuntimeError(f"{path.name} のPNGエンコードに失敗しました")
                zf.writestr(f"{folder}/{path.name}", encoded.tobytes())
        return buf.getvalue()

    def generate_4_patterns_from_pair(
        self,
        base_image: np.ndarray,
        eye_source: np.ndarray,
        eye_mask: np.ndarray,
        mouth_source: np.ndarray,
        mouth_mask: np.ndarray,
        feather_width: int,
        base_eye_on: bool,
        base_mouth_on: bool,
    ) -> list[np.ndarray]:
        masked_eye = None
        masked_mouth = None
        if eye_mask.max() > 0:
            masked_eye = self.compositor.apply_mask_to_diff(eye_source, eye_mask, feather_width)
        if mouth_mask.max() > 0:
            masked_mouth = self.compositor.apply_mask_to_diff(mouth_source, mouth_mask, feather_width)

        patterns = []
        for eye_on, mouth_on in [(False, False), (True, False), (False, True), (True, True)]:
            result = base_image.copy()
            if eye_on != base_eye_on and masked_eye is not None:
                result = self.compositor.composite(result, masked_eye)
            if mouth_on != base_mouth_on and masked_mouth is not None:
                result = self.compositor.composite(result, masked_mouth)
            patterns.append(result)
        return patterns

    def align_variant_to_base(self, base: np.ndarray, variant: np.ndarray) -> tuple[np.ndarray, bool, float]:
        try:
            base_bgr = self.to_bgr_for_diff(base)
            variant_bgr = self.to_bgr_for_diff(variant)
            result = self.aligner.align(base_bgr, variant_bgr)
            if result["success"] and result["matrix"] is not None:
                aligned = self.aligner.apply_transform(variant, result["matrix"], (base.shape[1], base.shape[0]))
                return aligned, True, float(result["score"])
            return variant.copy(), False, float(result.get("score", 0.0))
        except Exception:
            return variant.copy(), False, 0.0

    def build_auto_part_mask(self, base_image: np.ndarray, source_image: np.ndarray, part: str) -> Optional[np.ndarray]:
        if base_image is None or source_image is None:
            return None
        if source_image.shape[:2] != base_image.shape[:2]:
            source_image = cv2.resize(source_image, (base_image.shape[1], base_image.shape[0]), interpolation=cv2.INTER_LINEAR)

        base_bgr = self.to_bgr_for_diff(base_image)
        source_bgr = self.to_bgr_for_diff(source_image)
        diff = cv2.absdiff(base_bgr, source_bgr)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        nonzero = gray[gray > 0]
        if nonzero.size == 0:
            return np.zeros(gray.shape, dtype=np.uint8)
        threshold = max(10, int(nonzero.mean() + nonzero.std()))
        _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        mask = self.limit_mask_to_part_region(mask, part)

        h, w = mask.shape
        min_area = max(12, int(h * w * 0.00003))
        max_area = int(h * w * 0.08)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        cleaned = np.zeros_like(mask)
        keep_labels = self.select_part_component_labels(stats, part, h, w)
        for label in range(1, num_labels):
            area = stats[label, cv2.CC_STAT_AREA]
            if label in keep_labels and min_area <= area <= max_area:
                cleaned[labels == label] = 255

        if cleaned.max() == 0:
            cleaned = self.fallback_part_mask(mask, part, h, w)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)
        cleaned = cv2.dilate(cleaned, kernel, iterations=2)
        return self.expand_part_mask(cleaned, part)

    def select_part_component_labels(self, stats: np.ndarray, part: str, h: int, w: int) -> set[int]:
        candidates = []
        min_area = max(12, int(h * w * 0.00003))
        max_area = int(h * w * 0.08)
        for label in range(1, stats.shape[0]):
            x = stats[label, cv2.CC_STAT_LEFT]
            y = stats[label, cv2.CC_STAT_TOP]
            bw = stats[label, cv2.CC_STAT_WIDTH]
            bh = stats[label, cv2.CC_STAT_HEIGHT]
            area = stats[label, cv2.CC_STAT_AREA]
            if area < min_area or area > max_area:
                continue
            cx = x + bw / 2
            cy = y + bh / 2
            if part == "eye":
                if cy > h * 0.58:
                    continue
                score = area * (1.0 + abs(cx - w / 2) / max(1, w / 2))
            else:
                if cy < h * 0.55 or cx < w * 0.22 or cx > w * 0.78:
                    continue
                center_penalty = abs(cx - w / 2) / max(1, w / 2)
                score = area * (1.0 - min(0.8, center_penalty))
            candidates.append((score, label))
        candidates.sort(reverse=True)
        keep_count = 2 if part == "eye" else 1
        return {label for _, label in candidates[:keep_count]}

    def fallback_part_mask(self, mask: np.ndarray, part: str, h: int, w: int) -> np.ndarray:
        limited = np.zeros_like(mask)
        if part == "eye":
            limited[: int(h * 0.58), :] = mask[: int(h * 0.58), :]
        else:
            limited[int(h * 0.55):, int(w * 0.22): int(w * 0.78)] = mask[int(h * 0.55):, int(w * 0.22): int(w * 0.78)]
        return limited

    def limit_mask_to_part_region(self, mask: np.ndarray, part: str) -> np.ndarray:
        h, w = mask.shape
        limited = np.zeros_like(mask)
        if part == "eye":
            limited[: int(h * 0.58), :] = mask[: int(h * 0.58), :]
        else:
            limited[int(h * 0.55):, int(w * 0.22): int(w * 0.78)] = mask[int(h * 0.55):, int(w * 0.22): int(w * 0.78)]
        return limited

    def expand_part_mask(self, mask: np.ndarray, part: str) -> np.ndarray:
        if mask.max() == 0:
            return mask
        h, w = mask.shape
        if part == "eye":
            margin_x_ratio, margin_y_ratio, min_margin = 0.45, 0.90, 10
        else:
            margin_x_ratio, margin_y_ratio, min_margin = 0.40, 0.55, 8

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        expanded = mask.copy()
        for label in range(1, num_labels):
            x = stats[label, cv2.CC_STAT_LEFT]
            y = stats[label, cv2.CC_STAT_TOP]
            bw = stats[label, cv2.CC_STAT_WIDTH]
            bh = stats[label, cv2.CC_STAT_HEIGHT]
            area = stats[label, cv2.CC_STAT_AREA]
            if area < max(12, int(h * w * 0.00003)):
                continue
            mx = max(min_margin, int(bw * margin_x_ratio))
            my = max(min_margin, int(bh * margin_y_ratio))
            x1, y1 = max(0, x - mx), max(0, y - my)
            x2, y2 = min(w - 1, x + bw + mx), min(h - 1, y + bh + my)
            center = ((x1 + x2) // 2, (y1 + y2) // 2)
            axes = (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2))
            cv2.ellipse(expanded, center, axes, 0, 0, 360, 255, -1)

        kernel_size = 9 if part == "eye" else 7
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        expanded = cv2.morphologyEx(expanded, cv2.MORPH_CLOSE, kernel, iterations=1)
        if part == "mouth":
            expanded = self.limit_mask_to_part_region(expanded, part)
        return expanded

    def match_base_color_to_standard_if_needed(self, session: WebSession, base: np.ndarray) -> np.ndarray:
        if session.standard_path is None or session.emotion_label == "標準":
            return base
        try:
            reference = load_image_as_bgra(str(session.standard_path))
        except Exception:
            return base
        if reference.shape[:2] != base.shape[:2]:
            reference = cv2.resize(reference, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
        return self.match_generated_color_to_reference(reference, base)

    def match_generated_color_to_reference(self, reference: np.ndarray, generated: np.ndarray) -> np.ndarray:
        if reference is None or generated is None:
            return generated
        reference_bgr = self.to_bgr_for_diff(reference).astype(np.uint8)
        generated_bgr = self.to_bgr_for_diff(generated).astype(np.uint8)
        if reference_bgr.shape[:2] != generated_bgr.shape[:2]:
            generated_bgr = cv2.resize(generated_bgr, (reference_bgr.shape[1], reference_bgr.shape[0]))
        sample_mask = self.build_color_match_sample_mask(reference_bgr, generated_bgr)
        if int(sample_mask.sum()) < 100:
            sample_mask = self.build_stable_color_sample_mask(reference_bgr.shape[:2])
        corrected = self.apply_bgr_color_transfer(reference_bgr, generated_bgr, sample_mask)
        result = generated.copy()
        if result.ndim == 2:
            return cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY)
        if result.shape[:2] != corrected.shape[:2]:
            result = cv2.resize(result, (corrected.shape[1], corrected.shape[0]), interpolation=cv2.INTER_AREA)
        if result.shape[2] == 4:
            result[:, :, :3] = corrected
            return result
        result[:, :, :3] = corrected
        return result

    def apply_bgr_color_transfer(self, reference_bgr: np.ndarray, generated_bgr: np.ndarray, sample_mask: np.ndarray) -> np.ndarray:
        reference_float = reference_bgr.astype(np.float32)
        generated_float = generated_bgr.astype(np.float32)
        corrected = generated_float.copy()
        for channel in range(3):
            reference_values = reference_float[:, :, channel][sample_mask]
            generated_values = generated_float[:, :, channel][sample_mask]
            if reference_values.size < 100:
                continue
            reference_mean = float(reference_values.mean())
            generated_mean = float(generated_values.mean())
            reference_std = float(reference_values.std())
            generated_std = float(generated_values.std())
            gain = 1.0 if generated_std < 1.0 else reference_std / generated_std
            gain = max(0.85, min(1.15, gain))
            offset = max(-18.0, min(18.0, reference_mean - generated_mean * gain))
            corrected[:, :, channel] = corrected[:, :, channel] * gain + offset
        return np.clip(corrected, 0, 255).astype(np.uint8)

    def build_stable_color_sample_mask(self, shape: tuple[int, int]) -> np.ndarray:
        h, w = shape
        mask = np.ones((h, w), dtype=bool)
        mask[int(h * 0.12): int(h * 0.68), int(w * 0.03): int(w * 0.47)] = False
        mask[int(h * 0.12): int(h * 0.68), int(w * 0.53): int(w * 0.97)] = False
        mask[int(h * 0.54): int(h * 0.95), int(w * 0.26): int(w * 0.74)] = False
        return mask

    def build_color_match_sample_mask(self, base_bgr: np.ndarray, variant_bgr: np.ndarray) -> np.ndarray:
        diff = cv2.absdiff(base_bgr.astype(np.uint8), variant_bgr.astype(np.uint8))
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        sample_mask = gray < 28
        sample_mask[: int(h * 0.62), :] &= gray[: int(h * 0.62), :] < 18
        sample_mask[int(h * 0.50):, int(w * 0.18): int(w * 0.82)] = False
        return sample_mask

    def to_bgr_for_diff(self, image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            alpha = image[:, :, 3:4].astype(np.float32) / 255.0
            white = np.full_like(bgr, 255)
            return (bgr.astype(np.float32) * alpha + white.astype(np.float32) * (1 - alpha)).astype(np.uint8)
        return image[:, :, :3]

    def prepare_output_image(self, image: np.ndarray) -> np.ndarray:
        target_size = (320, 240)
        if image.shape[1] == target_size[0] and image.shape[0] == target_size[1]:
            return image
        return cv2.resize(image, target_size, interpolation=cv2.INTER_AREA)

    def decode_image_bytes(self, data: bytes) -> np.ndarray:
        image_buf = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(image_buf, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError("画像の読み込みに失敗しました")
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
        if image.shape[2] == 3:
            return cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        if image.shape[2] == 4:
            return image
        raise RuntimeError(f"未対応の画像形式です: {image.shape}")

    def decode_mask_data_url(self, data_url: str) -> np.ndarray:
        payload = data_url.split(",", 1)[1] if "," in data_url else data_url
        data = base64.b64decode(payload)
        image = self.decode_image_bytes(data)
        if image.shape[2] == 4:
            alpha = image[:, :, 3]
            gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
            mask = np.where(alpha > 0, gray, 0).astype(np.uint8)
        else:
            mask = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return np.where(mask > 32, 255, 0).astype(np.uint8)

    def safe_stem(self, filename: str) -> str:
        stem = Path(filename or "output").stem
        return self.safe_path_name(stem)

    def safe_path_name(self, name: str) -> str:
        safe = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name)
        safe = safe.strip().strip(".")
        return safe or "output"
