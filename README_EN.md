# Stack-chan Face Maker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

A tool for creating expression assets for Stack-chan / Stack CoreS3.

[日本語](README.md)

---

## Features

- Generate the opposite eye/mouth state from one base image using an image generation API
- Create four expression patterns from a base image and one generated/selected variant
- Save final assets at 320x240 for Stack CoreS3 / M5Stack CoreS3
- Auto-generate initial eye and mouth masks from image differences
- Align the variant image with AKAZE / ORB feature matching
- Draw and correct masks in a local browser-based web app
- The previous PySide6 GUI is still available
- Supports Japanese file paths

---

## Quick Start

### Step 1: Install

```bash
git clone https://github.com/rotejin/EasyPNGTuber.git
cd EasyPNGTuber
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

### Step 3: Create Stack-chan Face Assets

1. Select a standard/base face image.
   - 640x480 is recommended for editing.
   - Set the base eye and mouth state in the UI.
2. Generate or select the opposite-state variant image.
   - Available generation models include Gemini Nano Banana Pro, Gemini Nano Banana 2 Preview, Gemini Nano Banana, and OpenAI GPT Image 2.
   - Enter the API key for the selected provider, or use `GEMINI_API_KEY` / `OPENAI_API_KEY`.
   - Use the additional prompt field for extra instructions such as preserving hair, reducing blush, or adjusting mouth size. It is applied to both emotion and opposite-state generation.
3. Click "Create 4 Patterns".
4. Adjust eye and mouth masks if needed.
5. Save all four PNGs. The CoreS3 320x240 output option is enabled by default.

### PySide6 GUI

```bash
uv run python parts_mixer.py
```

---

## Output Folder and Files

The app creates a `{emotion}_{base}/` folder in the selected output directory and saves:

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
