# Stack-chan Face Maker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

Stack-chan / Stack CoreS3向けの表情差分画像を簡単に作成するツールです。

[English](README_EN.md)

---

## 特徴

- 1枚の基準画像からNano Banana Pro（Gemini API）で反対状態の画像を生成
- 基準画像と変化画像の2枚から、目ON/OFF × 口ON/OFFの4パターンを生成
- Stack CoreS3 / M5Stack CoreS3向けに320x240で保存
- 差分ベースの初期マスク生成
- AKAZE / ORB 特徴点マッチングによる高精度位置合わせ
- オーバーレイ表示で差分確認しながらマスク描画
- 日本語ファイルパス対応
- シンプルなGUI（PySide6）

---

## クイックスタート

### Step 1: ツールのインストール

```bash
# リポジトリをダウンロードまたはクローン
git clone https://github.com/rotejin/EasyPNGTuber.git
cd EasyPNGTuber

# 依存パッケージをインストール（仮想環境も自動作成）
uv sync
```

> [uv](https://docs.astral.sh/uv/) がインストールされていない場合: `pip install uv` または [公式サイト](https://docs.astral.sh/uv/getting-started/installation/) 参照

### Step 2: Stack-chan表情素材の作成

1. **アプリを起動**
   ```bash
   uv run python parts_mixer.py
   ```
   - Gemini APIキーは画面の「Gemini APIキー」に入力できます
   - 未入力の場合は環境変数 `GEMINI_API_KEY` を使用します
2. **基準画像を選択**
   - Stack-chanに表示したい基準表情を1枚選びます
   - 推奨作業サイズは640x480です
   - 基準画像の目/口状態をUIで指定します
3. **反対状態の画像を生成**
   - 「画像生成モデル」でGemini Nano Banana Pro、Gemini Nano Banana 2 Preview、Gemini Nano Banana、OpenAI GPT Image 2を選べます
   - 選んだモデルのAPIキーを入力して「反対状態の画像を生成...」を押します
   - 手元に画像がある場合は「変化画像を選択...」でも使えます
4. **4パターンを作成**
   - 「4パターンを作成」を押すと、差分マスクとプレビューが生成されます
   - 必要に応じて目・口マスクを微調整します
   - 「生成画像の色を基準画像に合わせる」はデフォルトONです。AI生成で肌や髪の色が少し変わる場合に有効です
   - フェザーはマスク境界をぼかす設定です。まずは5〜12px程度を推奨します
5. **保存**
   - 「CoreS3用 320x240で保存」はデフォルトONです
   - 「4パターン一括保存」で実機向けPNGを保存します

---

## 出力

Stack CoreS3 / M5Stack CoreS3のLCDは320x240です。このアプリでは編集・生成を640x480で行い、保存時に320x240へ縮小する運用を推奨します。

### 出力ファイル

- `{元画像名}_eyeOFF_mouthOFF.png` - 目OFF 口OFF
- `{元画像名}_eyeON_mouthOFF.png` - 目ON 口OFF
- `{元画像名}_eyeOFF_mouthON.png` - 目OFF 口ON
- `{元画像名}_eyeON_mouthON.png` - 目ON 口ON

---

## サンプル画像

`sample/` フォルダに動作確認用のサンプル画像が含まれています。

- `tomari_sample.png` - 2x2表情シートのサンプル

---

## トラブルシューティング

### ツールが起動しない

- Python 3.10以上がインストールされているか確認
- `.venv` フォルダを削除して `uv sync` を再実行

### 画像が読み込めない

- 対応形式: PNG, JPG, BMP, WebP
- 日本語ファイル名も対応しています

### 位置合わせがうまくいかない

- 画像の差異が大きすぎる場合は失敗することがあります
- 回転角が±30度を超える場合は対応できません

---

## 技術仕様

### 位置合わせアルゴリズム

- **AKAZE特徴点マッチング**（メイン）
- **ORB**（フォールバック）
- **RANSAC** によるアフィン変換推定

### 制限パラメータ

| パラメータ | 値 |
|-----------|-----|
| 最大回転角 | ±30度 |
| スケール範囲 | 0.8～1.2倍 |
| 成功スコア閾値 | 0.6以上 |

---

## 推奨環境

| 項目 | 要件 |
|------|------|
| Python | 3.10 以上 |
| OS | Windows / macOS / Linux |
| パッケージ管理 | [uv](https://docs.astral.sh/uv/) 推奨 |

---

## ファイル構成

```
EasyPNGTuber/
├── parts_mixer.py        # メインツール: パーツ合成
├── grid_tiler.py         # 画像タイリング
├── mask_composer.py      # マスク合成
├── simple_aligner_app.py # 位置合わせ
├── aligner.py            # 位置合わせエンジン
├── compositor.py         # 画像合成エンジン
├── cv2_utils.py          # OpenCVユーティリティ
├── mask_canvas.py        # マスクキャンバスUI
├── preview_widget.py     # プレビューUI
├── gemini_prompt.txt     # AI用プロンプト
├── pyproject.toml        # 依存パッケージ定義
└── sample/               # サンプル画像
```

---

## ライセンス

[MIT License](LICENSE)

Copyright (c) 2026 rotejin
