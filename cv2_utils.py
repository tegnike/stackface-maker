"""
OpenCVユーティリティ
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple


def load_image_as_bgra(path: str) -> np.ndarray:
    """画像をBGRAとして読み込み（アルファなしは255で補完）

    Args:
        path: 画像ファイルパス

    Returns:
        BGRA画像 (uint8)
    """
    # 日本語パス対応: np.fromfile + imdecode
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except (OSError, IOError) as e:
        raise ValueError(f"Failed to load image: {path}") from e
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"Failed to load image: {path}")
    
    if img.ndim == 2:  # グレースケール
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:  # BGR（アルファなし）
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        img[:, :, 3] = 255  # 不透明アルファ
    elif img.shape[2] == 4:  # BGRA
        pass  # そのまま
    else:
        raise ValueError(f"Unsupported image format: {img.shape}")
    
    return img


def load_image(filepath: str, flags: int = cv2.IMREAD_UNCHANGED) -> Optional[np.ndarray]:
    """
    画像を読み込み

    Args:
        filepath: ファイルパス
        flags: OpenCV読み込みフラグ

    Returns:
        画像配列、失敗時はNone
    """
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        return None

    # 日本語パス対応: np.fromfile + imdecode
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except (OSError, IOError) as e:
        print(f"Failed to read file: {filepath} ({e})")
        return None
    image = cv2.imdecode(buf, flags)
    if image is None:
        print(f"Failed to load image: {filepath}")
        return None

    return image


def save_image(filepath: str, image: np.ndarray) -> bool:
    """
    画像を保存

    Args:
        filepath: ファイルパス
        image: 画像配列

    Returns:
        成功時True
    """
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 日本語パス対応: imencode + tofile
        ext = path.suffix.lower()
        if ext in ('.jpg', '.jpeg'):
            ext = '.jpg'
        elif ext == '':
            # 拡張子なしの場合は.pngを付与
            ext = '.png'
            path = path.with_suffix('.png')
        success, buf = cv2.imencode(ext, image)
        if success:
            buf.tofile(str(path))
            return True
        return False
    except Exception as e:
        print(f"Save error: {e}")
        return False


def resize_image(image: np.ndarray, 
                 target_size: Optional[Tuple[int, int]] = None,
                 max_size: Optional[int] = None,
                 interpolation: int = cv2.INTER_AREA) -> np.ndarray:
    """
    画像をリサイズ
    
    Args:
        image: 入力画像
        target_size: 目標サイズ (w, h)
        max_size: 最大辺長（target_sizeがNoneの場合使用）
        interpolation: 補間方法
    
    Returns:
        リサイズ後画像
    """
    if target_size is not None:
        return cv2.resize(image, target_size, interpolation=interpolation)
    
    if max_size is not None:
        h, w = image.shape[:2]
        scale = min(max_size / max(h, w), 1.0)
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            return cv2.resize(image, (new_w, new_h), interpolation=interpolation)
    
    return image




def composite_images(background: np.ndarray, 
                    foreground: np.ndarray,
                    alpha: float = 1.0) -> np.ndarray:
    """
    画像を合成（前景はRGBA想定）
    """
    # 前景をリサイズ
    h, w = background.shape[:2]
    foreground_resized = cv2.resize(foreground, (w, h))
    
    # アルファチャンネル抽出
    if foreground_resized.shape[2] == 4:
        fg_alpha = foreground_resized[:, :, 3].astype(float) / 255.0 * alpha
        fg_rgb = foreground_resized[:, :, :3].astype(float)
    else:
        fg_alpha = np.full((h, w), alpha)
        fg_rgb = foreground_resized.astype(float)
    
    # 背景をfloatに
    if len(background.shape) == 3:
        bg_rgb = background[:, :, :3].astype(float)
    else:
        bg_rgb = cv2.cvtColor(background, cv2.COLOR_GRAY2BGR).astype(float)
    
    # アルファ合成
    result = np.zeros_like(bg_rgb)
    for c in range(3):
        result[:, :, c] = bg_rgb[:, :, c] * (1 - fg_alpha) + fg_rgb[:, :, c] * fg_alpha
    
    return result.astype(np.uint8)
