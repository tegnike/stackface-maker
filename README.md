# StackFace Maker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

Stack-chan / Stack CoreS3向けの表情差分画像を簡単に作成するローカルWebアプリです。

StackFace Maker は [EasyPNGTuber](https://github.com/rotejin/EasyPNGTuber) をベースに、Stack-chan / Stack CoreS3 向けの表情素材作成ツールとして大幅に再設計した派生プロジェクトです。

[English](README_EN.md)

---

## 特徴

- 1枚の基準画像からNano Banana Pro（Gemini API）で反対状態の画像を生成
- 基準画像と反対状態画像の2枚から、目ON/OFF × 口ON/OFFの4パターンを生成
- Stack CoreS3 / M5Stack CoreS3向けに320x240で保存
- 差分ベースの初期マスク生成
- AKAZE / ORB 特徴点マッチングによる高精度位置合わせ
- オーバーレイ表示で差分確認しながらマスク描画
- 日本語ファイルパス対応
- ブラウザで操作できるローカルWebアプリ

---

## クイックスタート

### Step 1: ツールのインストール

```bash
# リポジトリをダウンロードまたはクローン
git clone https://github.com/tegnike/stackface-maker.git
cd stackface-maker

# 依存パッケージをインストール（仮想環境も自動作成）
uv sync
```

> [uv](https://docs.astral.sh/uv/) がインストールされていない場合: `pip install uv` または [公式サイト](https://docs.astral.sh/uv/getting-started/installation/) 参照

### Step 2: Webアプリを起動

```bash
uv run python web_app.py
```

ブラウザで `http://127.0.0.1:8765` を開きます。

- Gemini / OpenAI APIキーは画面から入力できます
- 未入力の場合は環境変数 `GEMINI_API_KEY` / `OPENAI_API_KEY` を使用します
- 保存はZIPダウンロードです。ZIP内に `{感情}_{元画像名}/` フォルダと4枚のPNGが入ります

### Step 2.5: 最初の標準表情画像を用意する

まだ基準画像がない場合は、`sample/standard/eyeON_mouthON.png` を第一リファレンス、作りたいキャラクター画像を第二リファレンスとして画像生成すると作りやすいです。

- 第一リファレンス: 構図、顔の大きさ、目口ONの状態、Stack-chan表示用の見え方
- 第二リファレンス: キャラクターデザイン、髪型、目、服装、色

画像生成プロンプト例:

```text
Generate a StackFace Maker eyeON_mouthON standard face asset.
This is not a portrait. It is a cropped face texture for a 320x240 LCD.

Use reference image 1 as the strict composition and expression guide.
Use reference image 2 only as the character identity/design guide.

Absolutely critical composition rule:
- The outline of the face must be outside the canvas on all sides.
- Do not show the oval shape of the face.
- Do not show a chin, jawline, ears, neck, collar, shoulders, clothes, or hands.
- The bottom edge of the image must cut the face immediately below the small open mouth, before any chin or jawline can appear.
- The left and right edges must cut through side hair/cheeks, before ears can appear.
- The top edge must cut through bangs/hair.

Match reference image 1:
- 4:3 aspect ratio, preferably 640x480.
- Face-only extreme close-up.
- Both eyes open.
- Small natural open speaking mouth near the bottom edge.
- Nose is only a tiny dot.
- Blush marks on both cheeks.
- Flat clean anime style suitable for later eye/mouth mask generation.

Character to draw from reference image 2:
- Anime girl with long silver-white hair, twin side buns, straight bangs, blue eyes, fair skin, and a neat school-uniform look.
- Preserve only her character identity: silver-white hair with soft gray shadows, blue eyes, fair skin, and a soft neutral friendly expression.
- Long side hair may be visible only where it is cropped by the frame.
- Do not zoom out to show the full twin buns or uniform.

Background:
- Transparent background if supported. Otherwise use a plain flat white background.
- Never draw a checkerboard pattern, UI, device, title, text, watermark, or scenery.

Negative prompt:
portrait, full head, full face oval, chin, jawline, ears, neck, collar, uniform, shoulders, body, hands, full buns, visible twin buns, character sheet, grid, multiple poses, text, watermark, UI, device mockup, background scene, big smile, large mouth.

If there is any doubt, prioritize matching the crop and feature positions of reference image 1 over showing the complete character design from reference image 2.
```

### Step 3: Stack-chan表情素材の作成

0. **画像生成設定**
   - 「画像生成モデル」でGemini Nano Banana Pro、Gemini Nano Banana 2 Preview、Gemini Nano Banana、OpenAI GPT Image 2を選べます
   - 選んだモデルのAPIキーを入力します。未入力の場合は `GEMINI_API_KEY` / `OPENAI_API_KEY` を使用します
1. **標準表情を選択**
   - Stack-chanに表示したい基準表情を1枚選びます
   - 推奨作業サイズは640x480です
2. **感情画像を作成**
   - 基準画像の目/口状態をUIで指定します
   - 感情は「標準」「喜び」「悲しみ」「怒り」「考え中」から選べます
   - 一覧にない表情は、カスタム表情欄に名前を入れると、その名前で生成できます
   - 必要に応じて「感情画像用プロンプト」に表情の補足指示を入力できます
   - 「標準表情の画像」を元にして、他の感情は「この感情の画像を生成...」で作成できます
3. **反対状態の画像を生成**
   - 「反対状態の画像を生成...」を押します
   - 必要に応じて「反対状態用プロンプト」に髪型・頬・口の大きさなどの補足指示を入力できます
   - 手元に画像がある場合は「反対状態の画像を選択...」でも使えます
4. **4パターンを作成**
   - 「4パターンを作成」を押すと、差分マスクとプレビューが生成されます
   - 必要に応じて目・口マスクを微調整します
   - 「生成画像の色を基準画像に合わせる」はデフォルトONです。感情画像は標準表情の色へ、反対状態画像は基準画像の色へ寄せます
   - フェザーはマスク境界をぼかす設定です。まずは5〜12px程度を推奨します
5. **保存**
   - 「CoreS3用 320x240で保存」はデフォルトONです
   - 「4パターンをZIP保存」で、感情名を含むフォルダに実機向けPNGを保存します

## 出力

Stack CoreS3 / M5Stack CoreS3のLCDは320x240です。このアプリでは編集・生成を640x480で行い、保存時に320x240へ縮小する運用を推奨します。

### 出力フォルダとファイル

保存先フォルダの中に `{感情}_{元画像名}/` を作り、以下の4ファイルを保存します。

- `eyeOFF_mouthOFF.png` - 目OFF 口OFF
- `eyeON_mouthOFF.png` - 目ON 口OFF
- `eyeOFF_mouthON.png` - 目OFF 口ON
- `eyeON_mouthON.png` - 目ON 口ON

---

## サンプル画像

`sample/standard/` フォルダに、StackFace Makerで作成した4パターンのサンプル画像が含まれています。

- `eyeOFF_mouthOFF.png`
- `eyeON_mouthOFF.png`
- `eyeOFF_mouthON.png`
- `eyeON_mouthON.png`

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
stackface-maker/
├── web_app.py            # ローカルWebアプリ
├── web_image_service.py  # Webアプリ用の画像処理
├── web_static/           # Web UI
├── aligner.py            # 位置合わせエンジン
├── compositor.py         # 画像合成エンジン
├── cv2_utils.py          # OpenCVユーティリティ
├── gemini_generator.py   # Gemini画像生成
├── openai_generator.py   # OpenAI画像生成
├── pyproject.toml        # 依存パッケージ定義
└── sample/               # StackFace Makerの出力サンプル画像
```

---

## ライセンス

[MIT License](LICENSE)

Copyright (c) 2026 rotejin

このプロジェクトは EasyPNGTuber をベースにしています。詳細は [NOTICE.md](NOTICE.md) を参照してください。
