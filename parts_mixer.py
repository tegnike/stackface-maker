#!/usr/bin/env python3
"""
Parts Mixer - PNGTuberパーツ合成ツール

目と口のパーツを別々のソース画像から取得し、
4パターン（目ON/OFF x 口ON/OFF）を自動生成する。
"""
import sys
import os
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QMessageBox, QGroupBox,
    QSplitter, QScrollArea, QProgressDialog, QSpinBox, QSlider,
    QRadioButton, QButtonGroup, QComboBox, QGridLayout, QFrame,
    QCheckBox, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence

sys.path.insert(0, str(Path(__file__).parent))

from compositor import Compositor, CompositeConfig
from mask_canvas import MaskCanvas
from preview_widget import PreviewWidget
from cv2_utils import load_image_as_bgra, save_image, bgra_to_qimage
from mask_composer import SliceAlignWorker, SliceItem
from aligner import Aligner, AlignConfig
from gemini_generator import (
    DEFAULT_MODEL,
    GeminiImageGenerationError,
    build_counterpart_prompt,
    generate_counterpart_image,
    generate_expression_sheet,
)
from openai_generator import (
    DEFAULT_OPENAI_IMAGE_MODEL,
    OpenAIImageGenerationError,
    generate_counterpart_image_openai,
)


class GeminiGenerateWorker(QThread):
    """Nano Banana Proで表情シートを生成するワーカー"""

    progress = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        source_path: str,
        output_path: str,
        api_key: str,
        model: str,
        image_size: str,
        base_eye_on: bool = True,
        base_mouth_on: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path
        self.api_key = api_key
        self.model = model
        self.image_size = image_size
        self.base_eye_on = base_eye_on
        self.base_mouth_on = base_mouth_on

    def run(self):
        try:
            self.progress.emit('Nano Banana Proで表情シートを生成中...')
            result = generate_expression_sheet(
                api_key=self.api_key,
                image_path=self.source_path,
                model=self.model,
                image_size=self.image_size,
            )

            self.progress.emit('生成画像を640x480パネル用に整形中...')
            ref = load_image_as_bgra(self.source_path)
            target_w = ref.shape[1] * 2
            target_h = ref.shape[0] * 2

            image_buf = np.frombuffer(result.image_bytes, dtype=np.uint8)
            generated = cv2.imdecode(image_buf, cv2.IMREAD_UNCHANGED)
            if generated is None:
                raise GeminiImageGenerationError('生成画像の読み込みに失敗しました')

            if generated.ndim == 2:
                generated = cv2.cvtColor(generated, cv2.COLOR_GRAY2BGRA)
            elif generated.shape[2] == 3:
                generated = cv2.cvtColor(generated, cv2.COLOR_BGR2BGRA)
            elif generated.shape[2] != 4:
                raise GeminiImageGenerationError(f'未対応の生成画像形式です: {generated.shape}')

            generated = cv2.resize(generated, (target_w, target_h), interpolation=cv2.INTER_AREA)
            if not save_image(self.output_path, generated):
                raise GeminiImageGenerationError('生成画像の保存に失敗しました')

            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))


class GeminiVariantWorker(QThread):
    """2枚モード用の変化画像を生成するワーカー"""

    progress = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        source_path: str,
        output_path: str,
        provider: str,
        api_key: str,
        model: str,
        image_size: str,
        base_eye_on: bool = True,
        base_mouth_on: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.image_size = image_size
        self.base_eye_on = base_eye_on
        self.base_mouth_on = base_mouth_on

    def run(self):
        try:
            if self.provider == 'openai':
                self.progress.emit('OpenAIで変化画像を生成中...')
                prompt = build_counterpart_prompt(self.base_eye_on, self.base_mouth_on)
                result = generate_counterpart_image_openai(
                    api_key=self.api_key,
                    image_path=self.source_path,
                    prompt=prompt,
                    model=self.model,
                    size='auto',
                )
            else:
                self.progress.emit('Geminiで変化画像を生成中...')
                result = generate_counterpart_image(
                    api_key=self.api_key,
                    image_path=self.source_path,
                    base_eye_on=getattr(self, 'base_eye_on', True),
                    base_mouth_on=getattr(self, 'base_mouth_on', False),
                    model=self.model,
                    image_size=self.image_size,
                )

            ref = load_image_as_bgra(self.source_path)
            target_w = ref.shape[1]
            target_h = ref.shape[0]

            image_buf = np.frombuffer(result.image_bytes, dtype=np.uint8)
            generated = cv2.imdecode(image_buf, cv2.IMREAD_UNCHANGED)
            if generated is None:
                raise GeminiImageGenerationError('生成画像の読み込みに失敗しました')

            if generated.ndim == 2:
                generated = cv2.cvtColor(generated, cv2.COLOR_GRAY2BGRA)
            elif generated.shape[2] == 3:
                generated = cv2.cvtColor(generated, cv2.COLOR_BGR2BGRA)
            elif generated.shape[2] != 4:
                raise GeminiImageGenerationError(f'未対応の生成画像形式です: {generated.shape}')

            generated = cv2.resize(generated, (target_w, target_h), interpolation=cv2.INTER_AREA)
            if not save_image(self.output_path, generated):
                raise GeminiImageGenerationError('生成画像の保存に失敗しました')

            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))


class MaskCanvasWithOverlay(MaskCanvas):
    """オーバーレイ表示機能付きマスクキャンバス

    ソース画像とベース画像を半透明で重ねて表示し、
    差分領域を視覚的に把握しやすくする。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay_image: Optional[np.ndarray] = None  # ベース画像（オーバーレイ用）
        self._overlay_opacity: float = 0.5  # 0.0=ソースのみ, 1.0=ベースのみ

    def set_overlay_image(self, image: Optional[np.ndarray]):
        """オーバーレイ用ベース画像を設定"""
        if image is not None:
            self._overlay_image = image.copy()
        else:
            self._overlay_image = None
        self._update_display_pixmap()
        self.update()

    def set_overlay_opacity(self, opacity: float):
        """オーバーレイ透明度を設定（0.0〜1.0）"""
        self._overlay_opacity = max(0.0, min(1.0, opacity))
        self._update_display_pixmap()
        self.update()

    def _update_display_pixmap(self):
        """表示用ピクマップを更新（オーバーレイ合成付き）"""
        if self.base_image is None:
            return

        # オーバーレイ画像がある場合はブレンド
        if self._overlay_image is not None and self._overlay_opacity > 0:
            display_image = self._blend_with_overlay()
        else:
            display_image = self.base_image

        # QImageに変換
        qimage = bgra_to_qimage(display_image)
        self.display_pixmap = QPixmap.fromImage(qimage)

    def _blend_with_overlay(self) -> np.ndarray:
        """ソース画像とベース画像をブレンド"""
        source = self.base_image
        overlay = self._overlay_image

        # サイズが異なる場合はリサイズ
        if overlay.shape[:2] != source.shape[:2]:
            overlay = cv2.resize(overlay, (source.shape[1], source.shape[0]))

        # BGRAをBGRに変換してブレンド
        if source.shape[2] == 4:
            src_bgr = cv2.cvtColor(source, cv2.COLOR_BGRA2BGR)
            src_alpha = source[:, :, 3]
        else:
            src_bgr = source
            src_alpha = None

        if overlay.shape[2] == 4:
            ovl_bgr = cv2.cvtColor(overlay, cv2.COLOR_BGRA2BGR)
        else:
            ovl_bgr = overlay

        # ブレンド: ソース * (1-opacity) + オーバーレイ * opacity
        blended = cv2.addWeighted(
            src_bgr, 1 - self._overlay_opacity,
            ovl_bgr, self._overlay_opacity,
            0
        )

        # BGRAに戻す
        if src_alpha is not None:
            result = cv2.cvtColor(blended, cv2.COLOR_BGR2BGRA)
            result[:, :, 3] = src_alpha
            return result

        return blended


class QuadPreviewWidget(QWidget):
    """4パターン同時プレビューウィジェット"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._previews: List[PreviewWidget] = []
        self._labels = [
            '目OFF 口OFF',
            '目ON 口OFF',
            '目OFF 口ON',
            '目ON 口ON'
        ]

        self._setup_ui()

    def _setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(5)

        for i, label_text in enumerate(self._labels):
            row, col = divmod(i, 2)

            container = QFrame()
            container.setFrameStyle(QFrame.StyledPanel)
            container.setStyleSheet('background-color: #2d2d30; border: 1px solid #3e3e42;')

            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(5, 5, 5, 5)

            # ラベル
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet('color: #ccc; font-weight: bold; border: none;')
            container_layout.addWidget(label)

            # プレビュー
            preview = PreviewWidget()
            preview.setMinimumSize(150, 150)
            self._previews.append(preview)
            container_layout.addWidget(preview)

            layout.addWidget(container, row, col)

    def set_images(self, images: List[Optional[np.ndarray]]):
        """4枚の画像を設定"""
        for i, preview in enumerate(self._previews):
            if i < len(images) and images[i] is not None:
                preview.set_base_image(images[i])
            else:
                preview.set_base_image(None)

    def set_scale(self, scale: float):
        """全プレビューにスケールを適用"""
        for preview in self._previews:
            preview.set_scale(scale)

    def fit_to_window(self):
        """全プレビューをウィンドウにフィット"""
        for preview in self._previews:
            preview.fit_to_window()


class PartsMixerWindow(QMainWindow):
    """Parts Mixer メインウィンドウ"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Stack-chan Face Maker - CoreS3表情素材生成')
        self.setMinimumSize(1400, 900)
        self.setAcceptDrops(True)

        # データ
        self.source_image: Optional[np.ndarray] = None
        self.source_path: str = ''
        self.items: List[SliceItem] = []
        self.current_job_id: int = 0
        self.worker: Optional[SliceAlignWorker] = None
        self.gemini_worker: Optional[GeminiGenerateWorker] = None
        self.gemini_variant_worker: Optional[GeminiVariantWorker] = None
        self.compositor = Compositor(CompositeConfig())
        self.aligner = Aligner(AlignConfig())
        self.two_image_mode: bool = False
        self.base_eye_on: bool = False
        self.base_mouth_on: bool = False
        self.pair_base_path: str = ''
        self.pair_variant_path: str = ''
        self.selected_provider: str = 'gemini'
        self.selected_model: str = DEFAULT_MODEL

        # 選択インデックス
        self.base_index: int = 0
        self.eye_source_index: int = 1
        self.mouth_source_index: int = 2

        # 生成パターン
        self.generated_patterns: List[np.ndarray] = []

        # プレビュー更新デバウンス用タイマー
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)  # 200ms デバウンス
        self._preview_timer.timeout.connect(self._do_update_previews)

        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === 左パネル（コントロール） ===
        left_panel = QWidget()
        left_panel.setMinimumWidth(250)
        left_panel.setMaximumWidth(400)
        left_layout = QVBoxLayout(left_panel)

        # Nano Banana Pro生成（旧2x2ワークフロー。Stack-chan版では非表示）
        generate_group = QGroupBox('Nano Banana Pro生成')
        generate_layout = QVBoxLayout(generate_group)

        self.btn_generate_sheet = QPushButton('元画像から2x2生成...')
        self.btn_generate_sheet.setToolTip('GEMINI_API_KEYを使って、640x480などの元画像から2x2表情シートを生成します')
        self.btn_generate_sheet.clicked.connect(self._generate_with_nanobanana)
        generate_layout.addWidget(self.btn_generate_sheet)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel('生成サイズ:'))
        self.combo_gemini_size = QComboBox()
        self.combo_gemini_size.addItem('2K（推奨）', '2K')
        self.combo_gemini_size.addItem('1K（低コスト）', '1K')
        self.combo_gemini_size.addItem('4K（高品質）', '4K')
        size_layout.addWidget(self.combo_gemini_size)
        generate_layout.addLayout(size_layout)

        self.lbl_generate_status = QLabel('APIキー: GEMINI_API_KEY')
        self.lbl_generate_status.setStyleSheet('color: #888;')
        generate_layout.addWidget(self.lbl_generate_status)

        generate_group.setVisible(False)
        left_layout.addWidget(generate_group)

        # Stack-chan用1枚ワークフロー
        pair_group = QGroupBox('Stack-chan素材生成')
        pair_layout = QVBoxLayout(pair_group)

        self.btn_pair_base = QPushButton('基準画像を選択...')
        self.btn_pair_base.setToolTip('Stack-chanに表示する基準表情画像を選択します')
        self.btn_pair_base.setStyleSheet('background-color: #0e639c; color: white; min-height: 24px;')
        self.btn_pair_base.clicked.connect(self._select_pair_base)
        pair_layout.addWidget(self.btn_pair_base)

        self.lbl_pair_base = QLabel('基準: 未選択')
        self.lbl_pair_base.setStyleSheet('color: #888;')
        pair_layout.addWidget(self.lbl_pair_base)

        state_layout = QHBoxLayout()
        state_layout.addWidget(QLabel('基準の目:'))
        self.combo_base_eye_state = QComboBox()
        self.combo_base_eye_state.addItem('ON（開き）', True)
        self.combo_base_eye_state.addItem('OFF（閉じ）', False)
        self.combo_base_eye_state.currentIndexChanged.connect(self._on_base_state_changed)
        state_layout.addWidget(self.combo_base_eye_state)
        state_layout.addWidget(QLabel('口:'))
        self.combo_base_mouth_state = QComboBox()
        self.combo_base_mouth_state.addItem('OFF（閉じ）', False)
        self.combo_base_mouth_state.addItem('ON（開き）', True)
        self.combo_base_mouth_state.currentIndexChanged.connect(self._on_base_state_changed)
        state_layout.addWidget(self.combo_base_mouth_state)
        pair_layout.addLayout(state_layout)

        self.btn_pair_variant = QPushButton('変化画像を選択...')
        self.btn_pair_variant.setToolTip('基準画像と目/口が反対の画像を手動で選択します')
        self.btn_pair_variant.setStyleSheet('background-color: #0e639c; color: white; min-height: 24px;')
        self.btn_pair_variant.clicked.connect(self._select_pair_variant)
        pair_layout.addWidget(self.btn_pair_variant)

        self.lbl_pair_variant = QLabel('変化: 未選択')
        self.lbl_pair_variant.setStyleSheet('color: #888;')
        pair_layout.addWidget(self.lbl_pair_variant)

        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel('画像生成モデル:'))
        self.combo_image_model = QComboBox()
        self.combo_image_model.addItem('Gemini Nano Banana Pro（高品質）', ('gemini', DEFAULT_MODEL))
        self.combo_image_model.addItem('Gemini Nano Banana 2（Preview）', ('gemini', 'gemini-3.1-flash-image-preview'))
        self.combo_image_model.addItem('Gemini Nano Banana（高速）', ('gemini', 'gemini-2.5-flash-image'))
        self.combo_image_model.addItem('OpenAI GPT Image 2', ('openai', DEFAULT_OPENAI_IMAGE_MODEL))
        self.combo_image_model.currentIndexChanged.connect(self._on_image_model_changed)
        model_layout.addWidget(self.combo_image_model)
        pair_layout.addLayout(model_layout)

        api_layout = QHBoxLayout()
        self.lbl_gemini_api_key = QLabel('Gemini APIキー:')
        api_layout.addWidget(self.lbl_gemini_api_key)
        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText('未入力なら環境変数 GEMINI_API_KEY を使用')
        self.edit_api_key.setText(os.environ.get('GEMINI_API_KEY', ''))
        self.edit_api_key.setStyleSheet('background-color: #3c3c3c; color: white; border: 1px solid #3e3e42; padding: 4px;')
        api_layout.addWidget(self.edit_api_key)
        pair_layout.addLayout(api_layout)

        openai_api_layout = QHBoxLayout()
        self.lbl_openai_api_key = QLabel('OpenAI APIキー:')
        openai_api_layout.addWidget(self.lbl_openai_api_key)
        self.edit_openai_api_key = QLineEdit()
        self.edit_openai_api_key.setEchoMode(QLineEdit.Password)
        self.edit_openai_api_key.setPlaceholderText('未入力なら環境変数 OPENAI_API_KEY を使用')
        self.edit_openai_api_key.setText(os.environ.get('OPENAI_API_KEY', ''))
        self.edit_openai_api_key.setStyleSheet('background-color: #3c3c3c; color: white; border: 1px solid #3e3e42; padding: 4px;')
        openai_api_layout.addWidget(self.edit_openai_api_key)
        pair_layout.addLayout(openai_api_layout)
        self.lbl_openai_api_key.setVisible(False)
        self.edit_openai_api_key.setVisible(False)

        self.btn_generate_variant = QPushButton('反対状態の画像を生成...')
        self.btn_generate_variant.setToolTip('選択した画像生成モデルで、基準画像と目/口が反対の画像を生成します')
        self.btn_generate_variant.setStyleSheet('background-color: #0e639c; color: white; min-height: 24px;')
        self.btn_generate_variant.clicked.connect(self._generate_pair_variant_with_nanobanana)
        pair_layout.addWidget(self.btn_generate_variant)

        self.btn_setup_pair = QPushButton('4パターンを作成')
        self.btn_setup_pair.setStyleSheet('background-color: #2563eb; color: white; min-height: 24px;')
        self.btn_setup_pair.clicked.connect(self._setup_two_image_mode)
        self.btn_setup_pair.setEnabled(False)
        pair_layout.addWidget(self.btn_setup_pair)

        left_layout.addWidget(pair_group)

        # 分割サイズ選択
        grid_group = QGroupBox('分割サイズ')
        grid_layout = QHBoxLayout(grid_group)
        grid_layout.addWidget(QLabel('レイアウト:'))
        self.combo_grid = QComboBox()
        self.combo_grid.addItem('2x2（4枚）', 2)
        # self.combo_grid.addItem('3x3（9枚）', 3)  # Parts Mixerは2x2固定
        self.combo_grid.setCurrentIndex(0)
        self.combo_grid.currentIndexChanged.connect(self._on_grid_changed)
        grid_layout.addWidget(self.combo_grid)
        grid_group.setVisible(False)
        left_layout.addWidget(grid_group)

        # 画像入力
        drop_group = QGroupBox('画像入力')
        drop_layout = QVBoxLayout(drop_group)

        self.drop_zone = QLabel('表情シートをここにドロップ')
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setStyleSheet(
            "background-color: #1e1e1e; border: 2px dashed #3e3e42; "
            "border-radius: 5px; padding: 20px; color: #888;"
        )
        self.drop_zone.setMinimumHeight(80)
        drop_layout.addWidget(self.drop_zone)

        self.btn_select = QPushButton('ファイルを選択...')
        self.btn_select.clicked.connect(self._select_file)
        drop_layout.addWidget(self.btn_select)

        self.btn_process = QPushButton('分割＆位置合わせ')
        self.btn_process.setStyleSheet(
            'background-color: #2563eb; color: white; font-weight: bold; padding: 8px;'
        )
        self.btn_process.clicked.connect(self._execute_process)
        self.btn_process.setEnabled(False)
        drop_layout.addWidget(self.btn_process)

        drop_group.setVisible(False)
        left_layout.addWidget(drop_group)

        # 画像選択
        select_group = QGroupBox('画像選択')
        select_layout = QVBoxLayout(select_group)

        base_layout = QHBoxLayout()
        base_layout.addWidget(QLabel('ベース:'))
        self.combo_base = QComboBox()
        self.combo_base.currentIndexChanged.connect(self._on_base_changed)
        self.combo_base.setEnabled(False)
        base_layout.addWidget(self.combo_base)
        select_layout.addLayout(base_layout)

        eye_layout = QHBoxLayout()
        eye_layout.addWidget(QLabel('目ソース:'))
        self.combo_eye = QComboBox()
        self.combo_eye.currentIndexChanged.connect(self._on_eye_source_changed)
        self.combo_eye.setEnabled(False)
        eye_layout.addWidget(self.combo_eye)
        select_layout.addLayout(eye_layout)

        mouth_layout = QHBoxLayout()
        mouth_layout.addWidget(QLabel('口ソース:'))
        self.combo_mouth = QComboBox()
        self.combo_mouth.currentIndexChanged.connect(self._on_mouth_source_changed)
        self.combo_mouth.setEnabled(False)
        mouth_layout.addWidget(self.combo_mouth)
        select_layout.addLayout(mouth_layout)

        self.btn_auto_select = QPushButton('自動選択＆マスク更新')
        self.btn_auto_select.setToolTip('各コマの差分から目ソース・口ソースを推定し、初期マスクを作り直します')
        self.btn_auto_select.clicked.connect(self._auto_select_and_update_masks)
        self.btn_auto_select.setEnabled(False)
        select_layout.addWidget(self.btn_auto_select)

        select_group.setVisible(False)
        left_layout.addWidget(select_group)

        # ブラシ設定
        brush_group = QGroupBox('ブラシ')
        brush_layout = QVBoxLayout(brush_group)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel('サイズ:'))
        self.spin_brush_size = QSpinBox()
        self.spin_brush_size.setRange(1, 200)
        self.spin_brush_size.setValue(30)
        self.spin_brush_size.valueChanged.connect(self._on_brush_size_changed)
        size_layout.addWidget(self.spin_brush_size)
        brush_layout.addLayout(size_layout)

        self.btn_group_mode = QButtonGroup(self)
        self.radio_add = QRadioButton('マスクを塗る')
        self.radio_add.setChecked(True)
        self.radio_erase = QRadioButton('マスクを消す')
        mode_style = """
            QRadioButton { color: #9ca3af; padding: 4px; }
            QRadioButton:checked { color: white; font-weight: bold; }
            QRadioButton::indicator { width: 13px; height: 13px; }
            QRadioButton::indicator:unchecked { border: 1px solid #6b7280; border-radius: 7px; background: #252526; }
            QRadioButton::indicator:checked { border: 1px solid #60a5fa; border-radius: 7px; background: #2563eb; }
        """
        self.radio_add.setStyleSheet(mode_style)
        self.radio_erase.setStyleSheet(mode_style)
        self.btn_group_mode.addButton(self.radio_add)
        self.btn_group_mode.addButton(self.radio_erase)
        brush_layout.addWidget(self.radio_add)
        brush_layout.addWidget(self.radio_erase)

        self.radio_add.toggled.connect(self._on_mode_toggled)

        # Undo/Redo
        undo_layout = QHBoxLayout()
        self.btn_undo = QPushButton('戻す')
        self.btn_undo.setToolTip('Ctrl+Z')
        self.btn_undo.clicked.connect(self._on_undo)
        undo_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton('やり直し')
        self.btn_redo.setToolTip('Ctrl+Y')
        self.btn_redo.clicked.connect(self._on_redo)
        undo_layout.addWidget(self.btn_redo)
        brush_layout.addLayout(undo_layout)

        left_layout.addWidget(brush_group)

        # フェザー
        feather_group = QGroupBox('フェザー')
        feather_layout = QVBoxLayout(feather_group)
        feather_help = QLabel('マスクの境界をぼかして、目や口の貼り付け感を減らします。大きすぎると周囲も混ざります。')
        feather_help.setWordWrap(True)
        feather_help.setStyleSheet('color: #9ca3af; font-size: 11px;')
        feather_layout.addWidget(feather_help)
        feather_slider_layout = QHBoxLayout()
        feather_slider_layout.addWidget(QLabel('幅:'))
        self.slider_feather = QSlider(Qt.Horizontal)
        self.slider_feather.setRange(0, 50)
        self.slider_feather.setValue(10)
        self.slider_feather.valueChanged.connect(self._on_feather_changed)
        feather_slider_layout.addWidget(self.slider_feather)
        self.lbl_feather_value = QLabel('10px')
        feather_slider_layout.addWidget(self.lbl_feather_value)
        feather_layout.addLayout(feather_slider_layout)
        left_layout.addWidget(feather_group)

        # 保存
        save_group = QGroupBox('保存')
        save_layout = QVBoxLayout(save_group)
        self.check_resize_cores3 = QCheckBox('CoreS3用 320x240で保存')
        self.check_resize_cores3.setChecked(True)
        self.check_resize_cores3.setToolTip('M5Stack CoreS3 / Stack CoreS3 のLCD解像度に合わせて保存します')
        save_layout.addWidget(self.check_resize_cores3)

        self.btn_save = QPushButton('4パターン一括保存...')
        self.btn_save.setStyleSheet('background-color: #16a34a; color: white;')
        self.btn_save.clicked.connect(self._save_all)
        self.btn_save.setEnabled(False)
        save_layout.addWidget(self.btn_save)
        left_layout.addWidget(save_group)

        left_layout.addStretch()
        splitter.addWidget(left_panel)

        # === 中央パネル（マスクキャンバス） ===
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)

        # 目パーツセクション
        eye_group = QGroupBox('目パーツ - マスク描画')
        eye_layout = QVBoxLayout(eye_group)

        eye_overlay_layout = QHBoxLayout()
        eye_overlay_layout.addWidget(QLabel('ベース透過:'))
        self.slider_eye_overlay = QSlider(Qt.Horizontal)
        self.slider_eye_overlay.setRange(0, 100)
        self.slider_eye_overlay.setValue(50)
        self.slider_eye_overlay.valueChanged.connect(self._on_eye_overlay_changed)
        eye_overlay_layout.addWidget(self.slider_eye_overlay)
        self.lbl_eye_overlay = QLabel('50%')
        self.lbl_eye_overlay.setFixedWidth(40)
        eye_overlay_layout.addWidget(self.lbl_eye_overlay)

        self.btn_clear_eye = QPushButton('クリア')
        self.btn_clear_eye.clicked.connect(self._clear_eye_mask)
        eye_overlay_layout.addWidget(self.btn_clear_eye)
        eye_layout.addLayout(eye_overlay_layout)

        eye_scroll = QScrollArea()
        eye_scroll.setWidgetResizable(False)
        eye_scroll.setMinimumHeight(200)
        self.eye_canvas = MaskCanvasWithOverlay()
        self.eye_canvas.maskChanged.connect(self._on_eye_mask_changed)
        eye_scroll.setWidget(self.eye_canvas)
        eye_layout.addWidget(eye_scroll)

        center_layout.addWidget(eye_group)

        # 口パーツセクション
        mouth_group = QGroupBox('口パーツ - マスク描画')
        mouth_layout = QVBoxLayout(mouth_group)

        mouth_overlay_layout = QHBoxLayout()
        mouth_overlay_layout.addWidget(QLabel('ベース透過:'))
        self.slider_mouth_overlay = QSlider(Qt.Horizontal)
        self.slider_mouth_overlay.setRange(0, 100)
        self.slider_mouth_overlay.setValue(50)
        self.slider_mouth_overlay.valueChanged.connect(self._on_mouth_overlay_changed)
        mouth_overlay_layout.addWidget(self.slider_mouth_overlay)
        self.lbl_mouth_overlay = QLabel('50%')
        self.lbl_mouth_overlay.setFixedWidth(40)
        mouth_overlay_layout.addWidget(self.lbl_mouth_overlay)

        self.btn_clear_mouth = QPushButton('クリア')
        self.btn_clear_mouth.clicked.connect(self._clear_mouth_mask)
        mouth_overlay_layout.addWidget(self.btn_clear_mouth)
        mouth_layout.addLayout(mouth_overlay_layout)

        mouth_scroll = QScrollArea()
        mouth_scroll.setWidgetResizable(False)
        mouth_scroll.setMinimumHeight(200)
        self.mouth_canvas = MaskCanvasWithOverlay()
        self.mouth_canvas.maskChanged.connect(self._on_mouth_mask_changed)
        mouth_scroll.setWidget(self.mouth_canvas)
        mouth_layout.addWidget(mouth_scroll)

        center_layout.addWidget(mouth_group)

        splitter.addWidget(center_panel)

        # === 右パネル（プレビュー） ===
        right_panel = QWidget()
        right_panel.setMinimumWidth(400)
        right_layout = QVBoxLayout(right_panel)

        preview_group = QGroupBox('プレビュー（4パターン）')
        preview_layout = QVBoxLayout(preview_group)

        # ズームコントロール
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel('表示:'))

        self.btn_preview_zoom_out = QPushButton('[-]')
        self.btn_preview_zoom_out.setFixedWidth(35)
        self.btn_preview_zoom_out.clicked.connect(self._preview_zoom_out)
        zoom_layout.addWidget(self.btn_preview_zoom_out)

        self.lbl_preview_zoom = QLabel('100%')
        self.lbl_preview_zoom.setFixedWidth(45)
        self.lbl_preview_zoom.setAlignment(Qt.AlignCenter)
        zoom_layout.addWidget(self.lbl_preview_zoom)

        self.btn_preview_zoom_in = QPushButton('[+]')
        self.btn_preview_zoom_in.setFixedWidth(35)
        self.btn_preview_zoom_in.clicked.connect(self._preview_zoom_in)
        zoom_layout.addWidget(self.btn_preview_zoom_in)

        self.btn_preview_fit = QPushButton('フィット')
        self.btn_preview_fit.clicked.connect(self._preview_fit)
        zoom_layout.addWidget(self.btn_preview_fit)

        zoom_layout.addStretch()
        preview_layout.addLayout(zoom_layout)

        # 4パターンプレビュー
        self.quad_preview = QuadPreviewWidget()
        preview_layout.addWidget(self.quad_preview)

        right_layout.addWidget(preview_group)
        splitter.addWidget(right_panel)

        splitter.setSizes([300, 600, 500])
        main_layout.addWidget(splitter)

        # プレビューズームレベル
        self.preview_zoom_level = 1.0

        # 最後にアクティブだったキャンバス
        self._last_active_canvas: Optional[MaskCanvasWithOverlay] = None
        self.eye_canvas.installEventFilter(self)
        self.mouth_canvas.installEventFilter(self)

    def eventFilter(self, obj, event):
        """イベントフィルタでフォーカスを追跡"""
        if event.type() == event.Type.FocusIn:
            if obj == self.eye_canvas:
                self._last_active_canvas = self.eye_canvas
            elif obj == self.mouth_canvas:
                self._last_active_canvas = self.mouth_canvas
        elif event.type() == event.Type.MouseButtonPress:
            if obj == self.eye_canvas:
                self._last_active_canvas = self.eye_canvas
            elif obj == self.mouth_canvas:
                self._last_active_canvas = self.mouth_canvas
        return super().eventFilter(obj, event)

    def _setup_shortcuts(self):
        """ショートカットキー設定"""
        self.shortcut_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.shortcut_undo.activated.connect(self._on_undo)
        self.shortcut_redo = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.shortcut_redo.activated.connect(self._on_redo)

    # === Nano Banana Pro生成 ===

    def _generate_with_nanobanana(self):
        """元画像から2x2表情シートを生成"""
        if self.gemini_worker is not None and self.gemini_worker.isRunning():
            QMessageBox.warning(self, '警告', '生成中です。')
            return

        api_key = self._get_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                'APIキー未設定',
                'Nano Banana Pro生成にはGemini APIキーが必要です。画面に入力するか、環境変数 GEMINI_API_KEY を設定してください。'
            )
            return

        source_path, _ = QFileDialog.getOpenFileName(
            self, '元キャラクター画像を選択', '',
            '画像 (*.png *.jpg *.jpeg *.bmp *.webp)'
        )
        if not source_path:
            return

        source = Path(source_path)
        output_path = source.with_name(f'{source.stem}_nanobanana_2x2.png')
        if output_path.exists():
            reply = QMessageBox.question(
                self, '確認',
                f'生成先ファイルが既に存在します:\n{output_path}\n\n上書きしますか？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.progress = QProgressDialog('生成中...', 'キャンセル', 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setValue(0)

        self.gemini_worker = GeminiGenerateWorker(
            source_path=str(source_path),
            output_path=str(output_path),
            api_key=api_key,
            model=DEFAULT_MODEL,
            image_size=self.combo_gemini_size.currentData(),
        )
        self.gemini_worker.progress.connect(self._on_generate_progress)
        self.gemini_worker.finished.connect(self._on_generate_finished)
        self.gemini_worker.error.connect(self._on_generate_error)
        self.gemini_worker.start()

        self.progress.canceled.connect(self._on_generate_cancel)
        self.btn_generate_sheet.setEnabled(False)

    def _on_generate_progress(self, message: str):
        if hasattr(self, 'progress'):
            self.progress.setLabelText(message)
        self.lbl_generate_status.setText(message)
        self.lbl_generate_status.setStyleSheet('color: #60a5fa;')

    def _on_generate_finished(self, output_path: str):
        if hasattr(self, 'progress'):
            self.progress.close()
        self.btn_generate_sheet.setEnabled(True)
        self.lbl_generate_status.setText(f'生成完了: {Path(output_path).name}')
        self.lbl_generate_status.setStyleSheet('color: #4ade80;')

        self._load_image(output_path)
        if self.source_image is not None:
            self._execute_process()

    def _on_generate_error(self, message: str):
        if hasattr(self, 'progress'):
            self.progress.close()
        self.btn_generate_sheet.setEnabled(True)
        self.btn_generate_variant.setEnabled(True)
        self.lbl_generate_status.setText('生成失敗')
        self.lbl_generate_status.setStyleSheet('color: #f87171;')
        QMessageBox.warning(self, '生成エラー', message)

    def _on_generate_cancel(self):
        if self.gemini_worker:
            self.gemini_worker.requestInterruption()

    # === 2枚モード ===

    def _select_pair_base(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '基準画像を選択', '',
            '画像 (*.png *.jpg *.jpeg *.bmp *.webp)'
        )
        if not path:
            return
        self.pair_base_path = path
        self.lbl_pair_base.setText(f'基準: {Path(path).name}')
        self.lbl_pair_base.setStyleSheet('color: #4ade80;')
        self._update_pair_setup_state()

    def _select_pair_variant(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '変化画像を選択', '',
            '画像 (*.png *.jpg *.jpeg *.bmp *.webp)'
        )
        if not path:
            return
        self.pair_variant_path = path
        self.lbl_pair_variant.setText(f'変化: {Path(path).name}')
        self.lbl_pair_variant.setStyleSheet('color: #4ade80;')
        self._update_pair_setup_state()

    def _update_pair_setup_state(self):
        self.btn_setup_pair.setEnabled(bool(self.pair_base_path and self.pair_variant_path))

    def _on_base_state_changed(self):
        self.base_eye_on = bool(self.combo_base_eye_state.currentData())
        self.base_mouth_on = bool(self.combo_base_mouth_state.currentData())

    def _on_image_model_changed(self):
        provider, model = self.combo_image_model.currentData()
        self.selected_provider = provider
        self.selected_model = model
        is_openai = provider == 'openai'
        self.lbl_gemini_api_key.setVisible(not is_openai)
        self.edit_api_key.setVisible(not is_openai)
        self.lbl_openai_api_key.setVisible(is_openai)
        self.edit_openai_api_key.setVisible(is_openai)

    def _get_api_key(self) -> str:
        """画面入力を優先し、未入力なら環境変数を見る"""
        provider = getattr(self, 'selected_provider', 'gemini')
        if provider == 'openai':
            if hasattr(self, 'edit_openai_api_key'):
                key = self.edit_openai_api_key.text().strip()
                if key:
                    return key
            return os.environ.get('OPENAI_API_KEY', '').strip()

        if hasattr(self, 'edit_api_key'):
            key = self.edit_api_key.text().strip()
            if key:
                return key
        return os.environ.get('GEMINI_API_KEY', '').strip()

    def _generate_pair_variant_with_nanobanana(self):
        if not self.pair_base_path:
            QMessageBox.warning(self, '警告', '先に基準画像を選択してください。')
            return
        if self.gemini_variant_worker is not None and self.gemini_variant_worker.isRunning():
            QMessageBox.warning(self, '警告', '生成中です。')
            return

        api_key = self._get_api_key()
        if not api_key:
            provider_name = 'OpenAI' if getattr(self, 'selected_provider', 'gemini') == 'openai' else 'Gemini'
            env_name = 'OPENAI_API_KEY' if provider_name == 'OpenAI' else 'GEMINI_API_KEY'
            QMessageBox.warning(
                self,
                'APIキー未設定',
                f'{provider_name}での画像生成にはAPIキーが必要です。画面に入力するか、環境変数 {env_name} を設定してください。'
            )
            return

        source = Path(self.pair_base_path)
        self._on_base_state_changed()
        self._on_image_model_changed()
        target_eye = not self.base_eye_on
        target_mouth = not self.base_mouth_on
        eye_label = 'eyeON' if target_eye else 'eyeOFF'
        mouth_label = 'mouthON' if target_mouth else 'mouthOFF'
        provider_label = 'openai' if self.selected_provider == 'openai' else 'gemini'
        output_path = source.with_name(f'{source.stem}_{provider_label}_{eye_label}_{mouth_label}.png')
        if output_path.exists():
            reply = QMessageBox.question(
                self, '確認',
                f'生成先ファイルが既に存在します:\n{output_path}\n\n上書きしますか？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.progress = QProgressDialog('生成中...', 'キャンセル', 0, 0, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setValue(0)

        self.gemini_variant_worker = GeminiVariantWorker(
            source_path=str(source),
            output_path=str(output_path),
            provider=self.selected_provider,
            api_key=api_key,
            model=self.selected_model,
            image_size=self.combo_gemini_size.currentData(),
            base_eye_on=self.base_eye_on,
            base_mouth_on=self.base_mouth_on,
        )
        self.gemini_variant_worker.progress.connect(self._on_generate_progress)
        self.gemini_variant_worker.finished.connect(self._on_pair_variant_generated)
        self.gemini_variant_worker.error.connect(self._on_generate_error)
        self.gemini_variant_worker.start()

        self.progress.canceled.connect(self._on_generate_variant_cancel)
        self.btn_generate_variant.setEnabled(False)

    def _on_pair_variant_generated(self, output_path: str):
        if hasattr(self, 'progress'):
            self.progress.close()
        self.btn_generate_variant.setEnabled(True)
        self.pair_variant_path = output_path
        self.lbl_pair_variant.setText(f'変化: {Path(output_path).name}')
        self.lbl_pair_variant.setStyleSheet('color: #4ade80;')
        self._update_pair_setup_state()
        self._setup_two_image_mode()

    def _on_generate_variant_cancel(self):
        if self.gemini_variant_worker:
            self.gemini_variant_worker.requestInterruption()
        self.btn_generate_variant.setEnabled(True)

    def _setup_two_image_mode(self):
        if not self.pair_base_path or not self.pair_variant_path:
            QMessageBox.warning(self, '警告', '基準画像と変化画像を選択してください。')
            return

        try:
            base = load_image_as_bgra(self.pair_base_path)
            variant = load_image_as_bgra(self.pair_variant_path)
        except Exception as e:
            QMessageBox.warning(self, 'エラー', f'画像の読み込みに失敗しました: {e}')
            return

        base_size = (base.shape[1], base.shape[0])
        if variant.shape[:2] != base.shape[:2]:
            variant = cv2.resize(variant, base_size, interpolation=cv2.INTER_LINEAR)

        aligned_variant, success, score = self._align_variant_to_base(base, variant)

        self.current_job_id += 1
        self.two_image_mode = True
        self._on_base_state_changed()
        self.source_path = self.pair_base_path
        self.source_image = base
        self.items = [
            SliceItem(
                index=0,
                image=base,
                aligned_image=base.copy(),
                alignment_success=True,
                alignment_score=1.0,
                is_base=True,
            ),
            SliceItem(
                index=1,
                image=variant,
                aligned_image=aligned_variant,
                alignment_success=success,
                alignment_score=score,
                is_base=False,
            ),
        ]
        self.generated_patterns = []

        self._update_drop_zone_thumbnail(base)
        self._update_combos()
        self.base_index = 0
        self.eye_source_index = 1
        self.mouth_source_index = 1
        self._set_combo_to_data(self.combo_base, 0)
        self._set_combo_to_data(self.combo_eye, 1)
        self._set_combo_to_data(self.combo_mouth, 1)

        self.combo_base.setEnabled(True)
        self.combo_eye.setEnabled(True)
        self.combo_mouth.setEnabled(True)
        self.btn_auto_select.setEnabled(True)
        self.btn_process.setEnabled(False)
        self.btn_process.setText('2枚モード処理済み')
        self.btn_process.setStyleSheet(
            'background-color: #16a34a; color: white; font-weight: bold; padding: 8px;'
        )

        self._update_canvases()
        self._apply_auto_masks()
        self._schedule_preview_update()

    def _align_variant_to_base(self, base: np.ndarray, variant: np.ndarray) -> tuple:
        """変化画像を基準画像へ軽く位置合わせする"""
        try:
            base_bgr = self._to_bgr_for_diff(base)
            variant_bgr = self._to_bgr_for_diff(variant)
            result = self.aligner.align(base_bgr, variant_bgr)
            if result['success'] and result['matrix'] is not None:
                aligned = self.aligner.apply_transform(variant, result['matrix'], (base.shape[1], base.shape[0]))
                return aligned, True, result['score']
            return variant.copy(), False, result.get('score', 0.0)
        except Exception:
            return variant.copy(), False, 0.0

    # === ドラッグ&ドロップ ===

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.pair_base_path = path
            self.lbl_pair_base.setText(f'基準: {Path(path).name}')
            self.lbl_pair_base.setStyleSheet('color: #4ade80;')
            self._update_pair_setup_state()

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '画像を選択', '',
            '画像 (*.png *.jpg *.jpeg *.bmp *.webp)'
        )
        if path:
            self.pair_base_path = path
            self.lbl_pair_base.setText(f'基準: {Path(path).name}')
            self.lbl_pair_base.setStyleSheet('color: #4ade80;')
            self._update_pair_setup_state()

    def _load_image(self, path: str):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, '警告', '処理中です。')
            return

        try:
            image = load_image_as_bgra(path)
        except Exception as e:
            QMessageBox.warning(self, 'エラー', f'画像の読み込みに失敗: {e}')
            return

        h, w = image.shape[:2]
        grid_size = self.combo_grid.currentData()
        if h % grid_size != 0 or w % grid_size != 0:
            QMessageBox.warning(
                self, 'エラー',
                f'画像サイズは {grid_size}x{grid_size} で割り切れる必要があります。\n'
                f'現在: {w}x{h}'
            )
            return

        self.current_job_id += 1
        self.two_image_mode = False
        self.base_eye_on = False
        self.base_mouth_on = False
        self.source_image = image
        self.source_path = path
        self.items = []
        self.generated_patterns = []

        # サムネイル表示
        self._update_drop_zone_thumbnail(image)

        self.btn_process.setEnabled(True)
        self.btn_save.setEnabled(False)
        self._disable_combos()

    def _update_drop_zone_thumbnail(self, image: np.ndarray):
        """ドロップゾーンにサムネイル表示"""
        h, w = image.shape[:2]
        max_size = 60
        scale = min(max_size / w, max_size / h, 1.0)
        thumb_w, thumb_h = int(w * scale), int(h * scale)
        thumbnail = cv2.resize(image, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)

        qimage = bgra_to_qimage(thumbnail)
        pixmap = QPixmap.fromImage(qimage)
        self.drop_zone.setPixmap(pixmap)
        self.drop_zone.setStyleSheet(
            "background-color: #1e1e1e; border: 2px solid #4ade80; "
            "border-radius: 5px; padding: 10px;"
        )

    def _disable_combos(self):
        """コンボボックスを無効化"""
        self.combo_base.setEnabled(False)
        self.combo_eye.setEnabled(False)
        self.combo_mouth.setEnabled(False)
        self.btn_auto_select.setEnabled(False)

    def _on_grid_changed(self, index: int):
        """グリッドサイズ変更"""
        self.current_job_id += 1
        self.items = []
        self.generated_patterns = []
        self._update_combos()
        self._disable_combos()

        if self.source_image is not None:
            # グリッドサイズで割り切れるか検証
            grid_size = self.combo_grid.currentData()
            h, w = self.source_image.shape[:2]
            if h % grid_size != 0 or w % grid_size != 0:
                self.btn_process.setEnabled(False)
                QMessageBox.warning(
                    self, '警告',
                    f'現在の画像サイズ ({w}x{h}) は {grid_size}x{grid_size} で割り切れません。\n'
                    f'別の画像を読み込むか、分割サイズを変更してください。'
                )
            else:
                self.btn_process.setEnabled(True)
            self.btn_save.setEnabled(False)

    # === 処理実行 ===

    def _execute_process(self):
        if self.source_image is None:
            return

        self.progress = QProgressDialog('処理中...', 'キャンセル', 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setValue(0)

        grid_size = self.combo_grid.currentData()
        self.worker = SliceAlignWorker(self.source_image, self.current_job_id, grid_size)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_process_finished)
        self.worker.error.connect(self._on_process_error)
        self.worker.start()

        self.progress.canceled.connect(self._on_cancel)
        self.btn_process.setEnabled(False)
        self.combo_grid.setEnabled(False)

    def _on_progress(self, value: int, message: str):
        if hasattr(self, 'progress'):
            self.progress.setValue(value)
            self.progress.setLabelText(message)

    def _on_process_finished(self, result: tuple):
        job_id, items = result

        if job_id != self.current_job_id:
            return

        self.items = items
        self.progress.close()

        # コンボボックス更新・有効化
        self._update_combos()
        self._auto_select_sources_from_diffs()
        self.combo_base.setEnabled(True)
        self.combo_eye.setEnabled(True)
        self.combo_mouth.setEnabled(True)
        self.btn_auto_select.setEnabled(True)

        # キャンバス初期化
        self._update_canvases()
        self._apply_auto_masks()

        self.btn_process.setEnabled(True)
        self.btn_process.setText('[OK] 処理済み（再実行）')
        self.btn_process.setStyleSheet(
            'background-color: #16a34a; color: white; font-weight: bold; padding: 8px;'
        )
        self.combo_grid.setEnabled(True)

        # プレビュー更新
        self._schedule_preview_update()

    def _on_process_error(self, message: str):
        self.progress.close()
        QMessageBox.warning(self, 'エラー', message)
        self.btn_process.setEnabled(True)
        self.combo_grid.setEnabled(True)

    def _on_cancel(self):
        if self.worker:
            self.worker.requestInterruption()

    # === コンボボックス ===

    def _get_position_label(self, index: int, grid_size: int) -> str:
        """インデックスから位置ラベルを取得"""
        row = index // grid_size
        col = index % grid_size

        if grid_size == 2:
            positions = [['左上', '右上'], ['左下', '右下']]
        else:
            positions = [
                ['左上', '上', '右上'],
                ['左', '中央', '右'],
                ['左下', '下', '右下']
            ]
        return positions[row][col]

    def _update_combos(self):
        """コンボボックスを更新"""
        grid_size = self.combo_grid.currentData()
        total = len(self.items) if self.items else grid_size * grid_size

        for combo in [self.combo_base, self.combo_eye, self.combo_mouth]:
            combo.blockSignals(True)
            combo.clear()
            for i in range(total):
                if self.two_image_mode and total == 2:
                    label = '基準' if i == 0 else '変化'
                else:
                    label = self._get_position_label(i, grid_size)
                combo.addItem(f'画像{i + 1}（{label}）', i)
            combo.blockSignals(False)

        # デフォルト選択
        self.combo_base.setCurrentIndex(0)
        self.combo_eye.setCurrentIndex(min(1, total - 1))
        self.combo_mouth.setCurrentIndex(min(2, total - 1))

        self.base_index = 0
        self.eye_source_index = min(1, total - 1)
        self.mouth_source_index = min(2, total - 1)

    def _auto_select_sources_from_diffs(self):
        """固定配置が崩れても、差分位置から目・口ソースを推定する"""
        if len(self.items) < 2 or self.base_index >= len(self.items):
            return

        base = self.items[self.base_index].aligned_image
        if base is None:
            return

        scores = []
        for item in self.items:
            if item.index == self.base_index or item.aligned_image is None:
                continue
            upper_score, lower_score = self._part_diff_scores(base, item.aligned_image)
            scores.append((item.index, upper_score, lower_score))

        if not scores:
            return

        eye_index = max(scores, key=lambda s: s[1] - s[2] * 0.25)[0]
        mouth_index = max(scores, key=lambda s: s[2] - s[1] * 0.20)[0]

        self.eye_source_index = eye_index
        self.mouth_source_index = mouth_index
        self._set_combo_to_data(self.combo_eye, eye_index)
        self._set_combo_to_data(self.combo_mouth, mouth_index)

    def _part_diff_scores(self, base_image: np.ndarray, source_image: np.ndarray) -> tuple:
        """顔の上半分/下半分の差分量を返す"""
        if source_image.shape[:2] != base_image.shape[:2]:
            source_image = cv2.resize(
                source_image,
                (base_image.shape[1], base_image.shape[0]),
                interpolation=cv2.INTER_LINEAR
            )

        base_bgr = self._to_bgr_for_diff(base_image)
        source_bgr = self._to_bgr_for_diff(source_image)
        diff = cv2.absdiff(base_bgr, source_bgr)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        h, w = gray.shape
        upper = gray[: int(h * 0.58), :]
        lower = gray[int(h * 0.42):, :]
        return float(upper.mean()), float(lower.mean())

    def _set_combo_to_data(self, combo: QComboBox, value: int):
        """currentDataがvalueの項目を選択する"""
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                return

    def _auto_select_and_update_masks(self):
        """手動で自動選択と初期マスク生成をやり直す"""
        if not self.items:
            return
        self._auto_select_sources_from_diffs()
        self._update_canvases()
        self._apply_auto_masks()
        self._schedule_preview_update()

    def _on_base_changed(self, index: int):
        if index < 0:
            return
        data = self.combo_base.currentData()
        if data is not None:
            self.base_index = data
            self._update_canvases()
            self._schedule_preview_update()

    def _on_eye_source_changed(self, index: int):
        if index < 0:
            return
        data = self.combo_eye.currentData()
        if data is not None:
            self.eye_source_index = data
            self._update_eye_canvas()
            self._schedule_preview_update()

    def _on_mouth_source_changed(self, index: int):
        if index < 0:
            return
        data = self.combo_mouth.currentData()
        if data is not None:
            self.mouth_source_index = data
            self._update_mouth_canvas()
            self._schedule_preview_update()

    # === キャンバス更新 ===

    def _update_canvases(self):
        """両キャンバスを更新"""
        self._update_eye_canvas()
        self._update_mouth_canvas()

    def _update_eye_canvas(self):
        """目キャンバスを更新"""
        if not self.items:
            return

        if self.eye_source_index < len(self.items):
            eye_image = self.items[self.eye_source_index].aligned_image
            self.eye_canvas.set_image(eye_image)

        if self.base_index < len(self.items):
            base_image = self.items[self.base_index].aligned_image
            self.eye_canvas.set_overlay_image(base_image)
            self.eye_canvas.set_overlay_opacity(self.slider_eye_overlay.value() / 100.0)

    def _update_mouth_canvas(self):
        """口キャンバスを更新"""
        if not self.items:
            return

        if self.mouth_source_index < len(self.items):
            mouth_image = self.items[self.mouth_source_index].aligned_image
            self.mouth_canvas.set_image(mouth_image)

        if self.base_index < len(self.items):
            base_image = self.items[self.base_index].aligned_image
            self.mouth_canvas.set_overlay_image(base_image)
            self.mouth_canvas.set_overlay_opacity(self.slider_mouth_overlay.value() / 100.0)

    def _apply_auto_masks(self):
        """固定配置を前提に目・口マスクの初期案を自動生成"""
        if len(self.items) < 2:
            return
        if self.base_index >= len(self.items):
            return
        if self.eye_source_index >= len(self.items) or self.mouth_source_index >= len(self.items):
            return

        base = self.items[self.base_index].aligned_image
        eye_source = self.items[self.eye_source_index].aligned_image
        mouth_source = self.items[self.mouth_source_index].aligned_image

        eye_mask = self._build_auto_part_mask(base, eye_source, part='eye')
        mouth_mask = self._build_auto_part_mask(base, mouth_source, part='mouth')

        if eye_mask is not None and eye_mask.max() > 0:
            self.eye_canvas.set_mask(eye_mask)
        if mouth_mask is not None and mouth_mask.max() > 0:
            self.mouth_canvas.set_mask(mouth_mask)

    def _build_auto_part_mask(
        self,
        base_image: np.ndarray,
        source_image: np.ndarray,
        part: str,
    ) -> Optional[np.ndarray]:
        """差分から編集しやすい初期マスクを作る"""
        if base_image is None or source_image is None:
            return None

        if source_image.shape[:2] != base_image.shape[:2]:
            source_image = cv2.resize(
                source_image,
                (base_image.shape[1], base_image.shape[0]),
                interpolation=cv2.INTER_LINEAR
            )

        base_bgr = self._to_bgr_for_diff(base_image)
        source_bgr = self._to_bgr_for_diff(source_image)
        diff = cv2.absdiff(base_bgr, source_bgr)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        nonzero = gray[gray > 0]
        if nonzero.size == 0:
            return np.zeros(gray.shape, dtype=np.uint8)

        threshold = max(10, int(nonzero.mean() + nonzero.std()))
        _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        mask = self._limit_mask_to_part_region(mask, part)

        h, w = mask.shape
        min_area = max(12, int(h * w * 0.00003))
        max_area = int(h * w * 0.08)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        cleaned = np.zeros_like(mask)
        keep_labels = self._select_part_component_labels(stats, part, h, w)
        for label in range(1, num_labels):
            area = stats[label, cv2.CC_STAT_AREA]
            if label in keep_labels and min_area <= area <= max_area:
                cleaned[labels == label] = 255

        if cleaned.max() == 0:
            cleaned = self._fallback_part_mask(mask, part, h, w)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=1)
        cleaned = cv2.dilate(cleaned, kernel, iterations=2)
        cleaned = self._expand_part_mask(cleaned, part)
        return cleaned

    def _select_part_component_labels(self, stats: np.ndarray, part: str, h: int, w: int) -> set:
        """目/口らしい差分領域だけを選ぶ"""
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
            if part == 'eye':
                if cy > h * 0.58:
                    continue
                # 髪や眉の細い差分より、目まわりのまとまりを優先
                score = area * (1.0 + abs(cx - w / 2) / max(1, w / 2))
            else:
                if cy < h * 0.55:
                    continue
                if cx < w * 0.22 or cx > w * 0.78:
                    continue
                # 口は顔中央下の最大領域を優先し、左右の頬/目残りを落とす
                center_penalty = abs(cx - w / 2) / max(1, w / 2)
                score = area * (1.0 - min(0.8, center_penalty))
            candidates.append((score, label))

        candidates.sort(reverse=True)
        keep_count = 2 if part == 'eye' else 1
        return {label for _, label in candidates[:keep_count]}

    def _fallback_part_mask(self, mask: np.ndarray, part: str, h: int, w: int) -> np.ndarray:
        """候補選択が空になった時の保険"""
        limited = np.zeros_like(mask)
        if part == 'eye':
            y1, y2 = 0, int(h * 0.58)
            limited[y1:y2, :] = mask[y1:y2, :]
        else:
            y1, y2 = int(h * 0.55), h
            x1, x2 = int(w * 0.22), int(w * 0.78)
            limited[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
        return limited

    def _limit_mask_to_part_region(self, mask: np.ndarray, part: str) -> np.ndarray:
        """目と口の差分が混ざらないよう、おおまかな顔領域で分離する"""
        h, w = mask.shape
        limited = np.zeros_like(mask)
        if part == 'eye':
            y1, y2 = 0, int(h * 0.58)
            limited[y1:y2, :] = mask[y1:y2, :]
        else:
            y1, y2 = int(h * 0.55), h
            x1, x2 = int(w * 0.22), int(w * 0.78)
            limited[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
        return limited

    def _expand_part_mask(self, mask: np.ndarray, part: str) -> np.ndarray:
        """置換元の線が残らないよう、差分領域を少し広めに覆う"""
        if mask.max() == 0:
            return mask

        h, w = mask.shape
        if part == 'eye':
            margin_x_ratio = 0.45
            margin_y_ratio = 0.90
            min_margin = 10
        else:
            margin_x_ratio = 0.40
            margin_y_ratio = 0.55
            min_margin = 8

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
            x1 = max(0, x - mx)
            y1 = max(0, y - my)
            x2 = min(w - 1, x + bw + mx)
            y2 = min(h - 1, y + bh + my)
            center = ((x1 + x2) // 2, (y1 + y2) // 2)
            axes = (max(1, (x2 - x1) // 2), max(1, (y2 - y1) // 2))
            cv2.ellipse(expanded, center, axes, 0, 0, 360, 255, -1)

        kernel_size = 9 if part == 'eye' else 7
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        expanded = cv2.morphologyEx(expanded, cv2.MORPH_CLOSE, kernel, iterations=1)
        if part == 'mouth':
            expanded = self._limit_mask_to_part_region(expanded, part)
        return expanded

    def _to_bgr_for_diff(self, image: np.ndarray) -> np.ndarray:
        """BGRA/BGR/GRAYを差分計算用BGRに変換"""
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            alpha = image[:, :, 3:4].astype(np.float32) / 255.0
            white = np.full_like(bgr, 255)
            return (bgr.astype(np.float32) * alpha + white.astype(np.float32) * (1 - alpha)).astype(np.uint8)
        return image[:, :, :3]

    # === ブラシ設定 ===

    def _on_brush_size_changed(self, value: int):
        self.eye_canvas.set_brush_size(value)
        self.mouth_canvas.set_brush_size(value)

    def _on_mode_toggled(self, checked: bool):
        mode = 'add' if self.radio_add.isChecked() else 'erase'
        self.eye_canvas.set_brush_mode(mode)
        self.mouth_canvas.set_brush_mode(mode)

    def _clear_eye_mask(self):
        self.eye_canvas.clear_mask()
        self._schedule_preview_update()

    def _clear_mouth_mask(self):
        self.mouth_canvas.clear_mask()
        self._schedule_preview_update()

    # === オーバーレイ透明度 ===

    def _on_eye_overlay_changed(self, value: int):
        self.lbl_eye_overlay.setText(f'{value}%')
        self.eye_canvas.set_overlay_opacity(value / 100.0)

    def _on_mouth_overlay_changed(self, value: int):
        self.lbl_mouth_overlay.setText(f'{value}%')
        self.mouth_canvas.set_overlay_opacity(value / 100.0)

    # === フェザー ===

    def _on_feather_changed(self, value: int):
        self.lbl_feather_value.setText(f'{value}px')
        self._schedule_preview_update()

    # === マスク変更 ===

    def _on_eye_mask_changed(self, mask: np.ndarray):
        self._last_active_canvas = self.eye_canvas
        self._schedule_preview_update()

    def _on_mouth_mask_changed(self, mask: np.ndarray):
        self._last_active_canvas = self.mouth_canvas
        self._schedule_preview_update()

    # === プレビュー更新（デバウンス付き） ===

    def _schedule_preview_update(self):
        """プレビュー更新をスケジュール（デバウンス）"""
        self._preview_timer.start()

    def _do_update_previews(self):
        """実際のプレビュー更新"""
        if not self.items:
            return

        eye_mask = self.eye_canvas.get_mask()
        mouth_mask = self.mouth_canvas.get_mask()

        if eye_mask is None or mouth_mask is None:
            return

        if self.base_index >= len(self.items):
            return
        if self.eye_source_index >= len(self.items):
            return
        if self.mouth_source_index >= len(self.items):
            return

        feather_width = self.slider_feather.value()
        base_image = self.items[self.base_index].aligned_image
        eye_source = self.items[self.eye_source_index].aligned_image
        mouth_source = self.items[self.mouth_source_index].aligned_image

        if self.two_image_mode:
            patterns = self._generate_4_patterns_from_pair(
                base_image, eye_source, eye_mask,
                mouth_source, mouth_mask, feather_width
            )
        else:
            patterns = self._generate_4_patterns(
                base_image, eye_source, eye_mask,
                mouth_source, mouth_mask, feather_width
            )

        self.generated_patterns = patterns
        self.quad_preview.set_images(patterns)

        if patterns:
            self.btn_save.setEnabled(True)

    def _generate_4_patterns(
        self,
        base_image: np.ndarray,
        eye_source: np.ndarray,
        eye_mask: np.ndarray,
        mouth_source: np.ndarray,
        mouth_mask: np.ndarray,
        feather_width: int
    ) -> List[np.ndarray]:
        """4パターンを生成"""
        # マスク適用を事前計算（パフォーマンス最適化）
        masked_eye = None
        masked_mouth = None

        if eye_mask.max() > 0:
            masked_eye = self.compositor.apply_mask_to_diff(
                eye_source, eye_mask, feather_width
            )

        if mouth_mask.max() > 0:
            masked_mouth = self.compositor.apply_mask_to_diff(
                mouth_source, mouth_mask, feather_width
            )

        patterns = []

        pattern_order = [
            (False, False),  # 目OFF 口OFF
            (True, False),   # 目ON 口OFF
            (False, True),   # 目OFF 口ON
            (True, True),    # 目ON 口ON
        ]

        for eye_on, mouth_on in pattern_order:
            result = base_image.copy()

            if eye_on and masked_eye is not None:
                result = self.compositor.composite(result, masked_eye)

            if mouth_on and masked_mouth is not None:
                result = self.compositor.composite(result, masked_mouth)

            patterns.append(result)

        return patterns

    def _generate_4_patterns_from_pair(
        self,
        base_image: np.ndarray,
        eye_source: np.ndarray,
        eye_mask: np.ndarray,
        mouth_source: np.ndarray,
        mouth_mask: np.ndarray,
        feather_width: int
    ) -> List[np.ndarray]:
        """2枚モード: 基準画像の状態を踏まえて4パターンを生成"""
        masked_eye = None
        masked_mouth = None

        if eye_mask.max() > 0:
            masked_eye = self.compositor.apply_mask_to_diff(
                eye_source, eye_mask, feather_width
            )

        if mouth_mask.max() > 0:
            masked_mouth = self.compositor.apply_mask_to_diff(
                mouth_source, mouth_mask, feather_width
            )

        pattern_order = [
            (False, False),  # 目OFF 口OFF
            (True, False),   # 目ON 口OFF
            (False, True),   # 目OFF 口ON
            (True, True),    # 目ON 口ON
        ]

        patterns = []
        for eye_on, mouth_on in pattern_order:
            result = base_image.copy()

            if eye_on != self.base_eye_on and masked_eye is not None:
                result = self.compositor.composite(result, masked_eye)

            if mouth_on != self.base_mouth_on and masked_mouth is not None:
                result = self.compositor.composite(result, masked_mouth)

            patterns.append(result)

        return patterns

    # === プレビューズーム ===

    def _preview_zoom_in(self):
        self.preview_zoom_level = min(3.0, self.preview_zoom_level * 1.25)
        self._apply_preview_zoom()

    def _preview_zoom_out(self):
        self.preview_zoom_level = max(0.25, self.preview_zoom_level / 1.25)
        self._apply_preview_zoom()

    def _preview_fit(self):
        self.quad_preview.fit_to_window()
        self.preview_zoom_level = 1.0
        self.lbl_preview_zoom.setText('Fit')

    def _apply_preview_zoom(self):
        self.quad_preview.set_scale(self.preview_zoom_level)
        self.lbl_preview_zoom.setText(f'{int(self.preview_zoom_level * 100)}%')

    # === Undo/Redo ===

    def _on_undo(self):
        """Undo実行（最後にアクティブだったキャンバス）"""
        canvas = self._last_active_canvas or self.eye_canvas
        if canvas.undo():
            self._schedule_preview_update()

    def _on_redo(self):
        """Redo実行（最後にアクティブだったキャンバス）"""
        canvas = self._last_active_canvas or self.eye_canvas
        if canvas.redo():
            self._schedule_preview_update()

    # === 保存 ===

    def _save_all(self):
        if not self.generated_patterns:
            QMessageBox.warning(self, '警告', '保存する画像がありません')
            return

        output_dir = QFileDialog.getExistingDirectory(self, '保存先フォルダを選択')
        if not output_dir:
            return

        output_path = Path(output_dir)
        base_name = Path(self.source_path).stem if self.source_path else 'output'

        # 既存ファイルチェック
        names = [
            f'{base_name}_eyeOFF_mouthOFF.png',
            f'{base_name}_eyeON_mouthOFF.png',
            f'{base_name}_eyeOFF_mouthON.png',
            f'{base_name}_eyeON_mouthON.png'
        ]

        existing = [n for n in names if (output_path / n).exists()]
        if existing:
            reply = QMessageBox.question(
                self, '確認',
                f'以下のファイルが既に存在します:\n{", ".join(existing)}\n\n上書きしますか？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        saved = 0
        for i, (name, image) in enumerate(zip(names, self.generated_patterns)):
            try:
                output_image = self._prepare_output_image(image)
                save_image(str(output_path / name), output_image)
                saved += 1
            except Exception as e:
                QMessageBox.warning(self, 'エラー', f'{name} の保存に失敗: {e}')

        QMessageBox.information(
            self, '完了',
            f'{saved} 枚の画像を保存しました:\n{output_dir}'
        )

    def _prepare_output_image(self, image: np.ndarray) -> np.ndarray:
        """保存用画像を必要に応じて実機サイズへ変換"""
        if not self.check_resize_cores3.isChecked():
            return image
        target_size = (320, 240)
        if image.shape[1] == target_size[0] and image.shape[0] == target_size[1]:
            return image
        return cv2.resize(image, target_size, interpolation=cv2.INTER_AREA)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Stack-chan Face Maker')
    app.setStyle('Fusion')

    app.setStyleSheet("""
        QMainWindow { background-color: #1e1e1e; }
        QWidget { background-color: #252526; color: #cccccc; }
        QPushButton { background-color: #0e639c; color: white; border: none; padding: 5px 15px; border-radius: 3px; }
        QPushButton:hover { background-color: #1177bb; }
        QPushButton:pressed { background-color: #094771; }
        QPushButton:disabled { background-color: #3c3c3c; color: #666; }
        QGroupBox { border: 1px solid #3e3e42; margin-top: 10px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QLabel { color: #cccccc; }
        QScrollArea { background-color: #1e1e1e; border: none; }
        QRadioButton { color: #ccc; }
        QSpinBox { background-color: #3c3c3c; border: 1px solid #3e3e42; padding: 3px; }
        QSlider::groove:horizontal { background: #3c3c3c; height: 6px; border-radius: 3px; }
        QSlider::handle:horizontal { background: #0e639c; width: 14px; margin: -4px 0; border-radius: 7px; }
        QComboBox { background-color: #3c3c3c; border: 1px solid #3e3e42; padding: 3px; }
        QComboBox::drop-down { border: none; }
        QComboBox QAbstractItemView { background-color: #3c3c3c; selection-background-color: #0e639c; }
    """)

    window = PartsMixerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
