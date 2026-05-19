# StackFace Maker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

A local web app for creating expression assets for Stack-chan / Stack CoreS3.

StackFace Maker is derived from [EasyPNGTuber](https://github.com/rotejin/EasyPNGTuber) and has been substantially redesigned for Stack-chan / Stack CoreS3 face asset creation.

[日本語](README.md)

---

## Features

- Generate the first standard face image from a character reference image
- Generate the opposite eye/mouth state from one base image using an image generation API
- Create four expression patterns from a base image and one generated/selected variant
- Save final assets at 320x240 for Stack CoreS3 / M5Stack CoreS3
- Auto-generate initial eye and mouth masks from image differences
- Align the variant image with AKAZE / ORB feature matching
- Draw and correct masks in a local browser-based web app
- Supports Japanese file paths

---

## Quick Start

### Step 1: Install

```bash
git clone https://github.com/tegnike/stackface-maker.git
cd stackface-maker
uv sync
```

### Step 2: Start the Web App

```bash
uv run python web_app.py
```

Open `http://127.0.0.1:8765` in your browser.

- API keys can be entered in the UI.
- If left empty, the app uses `GEMINI_API_KEY` / `OPENAI_API_KEY`.
- Save downloads a ZIP containing a `{emotion}_{base}/` folder with the four PNGs.

### Optional: Prepare the First Standard Face Image

If you do not have a base image yet, open the "Standard Face Generation" tab, select a character image, and click "Generate Standard Face". If you already have a standard face image, skip this optional step and continue to the "Create 4 Patterns" tab. The app uses `sample/standard/eyeON_mouthON.png` as the first reference image and your selected character image as the second reference image.

- Reference image 1: composition, face size, eye/mouth ON state, and Stack-chan display framing
- Reference image 2: character design, hairstyle, eyes, clothing, and colors
- If the result looks good, click "Use this image as the standard face" to continue into the normal four-pattern workflow
- Use the preset extra instructions such as "more close-up", "smaller mouth", "prioritize composition", and "stronger character features" when regenerating

Example prompt for external image generation tools or custom extra instructions:

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

### Step 3: Create Stack-chan Face Assets

0. Select a generation model and enter the provider API key.
   - If left blank, the app uses `GEMINI_API_KEY` / `OPENAI_API_KEY`.
1. Select a standard/base face image.
   - Use the "Create 4 Patterns" tab for this main workflow.
   - 640x480 is recommended for editing.
   - Set the base eye and mouth state in the UI.
   - Choose a preset emotion, or enter a temporary custom emotion label such as "surprised" or "sleepy".
   - Use the emotion prompt field for extra instructions when generating the emotion base image.
2. Generate or select the opposite-state variant image.
   - Available generation models include Gemini Nano Banana Pro, Gemini Nano Banana 2 Preview, Gemini Nano Banana, and OpenAI GPT Image 2.
   - Use the opposite-state prompt field for extra instructions such as preserving hair, reducing blush, or adjusting mouth size.
3. Click "Create 4 Patterns".
4. Adjust eye and mouth masks if needed.
5. Save all four PNGs. The CoreS3 320x240 output option is enabled by default.

## Output Folder and Files

The app creates a `{emotion}_{base}/` folder in the selected output directory and saves:

- `eyeOFF_mouthOFF.png`
- `eyeON_mouthOFF.png`
- `eyeOFF_mouthON.png`
- `eyeON_mouthON.png`

---

## Sample Images

`sample/standard/` contains a real four-pattern output sample:

- `eyeOFF_mouthOFF.png`
- `eyeON_mouthOFF.png`
- `eyeOFF_mouthON.png`
- `eyeON_mouthON.png`

---

## Requirements

| Item | Requirement |
|------|-------------|
| Python | 3.10+ |
| OS | Windows / macOS / Linux |
| Package manager | `uv` recommended |

---

## License

MIT License. See [LICENSE](LICENSE).

This project is derived from EasyPNGTuber. See [NOTICE.md](NOTICE.md) for attribution details.
