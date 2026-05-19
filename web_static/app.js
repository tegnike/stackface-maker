const state = {
  sessionId: null,
  characterUrl: "",
  generatedStandardUrl: "",
  standardUrl: "",
  baseUrl: "",
  variantUrl: "",
  patterns: [],
  paintMode: "paint",
  drawing: false,
  activeCanvas: null,
  busyCount: 0,
  maskZoom: 1,
  previewZoom: 1,
  maskFit: true,
  previewFit: true,
  previewBaseWidth: 320,
  renderTimer: null,
  renderRunning: false,
  renderQueued: false,
  patternsReady: false,
  statusTimer: null,
};

const $ = (id) => document.getElementById(id);

const patternLabels = ["目OFF 口OFF", "目ON 口OFF", "目OFF 口ON", "目ON 口ON"];
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

function cacheBust(url) {
  if (!url) return "";
  return `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

function setStatus(message, kind = "") {
  const el = $("status");
  window.clearTimeout(state.statusTimer);
  el.textContent = message;
  el.className = `status ${kind}`;
  const timeout = kind === "error" ? 8000 : 4000;
  state.statusTimer = window.setTimeout(() => {
    el.classList.add("hidden");
  }, timeout);
}

function showBusy(message = "処理中...") {
  state.busyCount += 1;
  $("busyMessage").textContent = message;
  $("busyOverlay").classList.remove("hidden");
}

function hideBusy() {
  state.busyCount = Math.max(0, state.busyCount - 1);
  if (state.busyCount === 0) {
    $("busyOverlay").classList.add("hidden");
  }
}

async function withBusy(message, task) {
  showBusy(message);
  try {
    return await task();
  } finally {
    hideBusy();
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

function boolValue(id) {
  return $(id).value === "true";
}

function modelParts() {
  const [provider, model] = $("modelSelect").value.split("|");
  return { provider, model };
}

async function initSession() {
  const data = await api("/api/session", { method: "POST" });
  state.sessionId = data.sessionId;
  setStatus("準備完了", "ok");
}

function showImage(id, url) {
  const img = $(id);
  img.src = cacheBust(url);
  img.classList.remove("hidden");
}

async function upload(role, file, extra = {}) {
  if (!file) return null;
  const form = new FormData();
  form.append("sessionId", state.sessionId);
  for (const [key, value] of Object.entries(extra)) {
    form.append(key, value);
  }
  form.append("file", file);
  return api(`/api/upload/${role}`, { method: "POST", body: form });
}

function selectedEmotion() {
  const custom = $("customEmotionName")?.value.trim() || "";
  if (custom) {
    return {
      emotion: "custom",
      label: custom,
    };
  }
  const option = $("emotionSelect").selectedOptions[0];
  return {
    emotion: option.value,
    label: option.dataset.label || option.textContent,
  };
}

async function updateEmotionControls() {
  const { emotion } = selectedEmotion();
  const isNeutral = emotion === "neutral";
  $("generateEmotion").classList.toggle("hidden", isNeutral);
  $("emotionOr").classList.toggle("hidden", isNeutral);
  $("emotionFileLabel").classList.toggle("hidden", isNeutral);
  if (isNeutral && state.standardUrl) {
    try {
      const data = await api("/api/use-standard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: state.sessionId }),
      });
      state.baseUrl = data.url;
      state.variantUrl = "";
      showImage("basePreview", state.baseUrl);
      $("baseName").textContent = "感情画像: 標準表情を使用";
      $("variantName").textContent = "反対状態画像: 未選択";
      $("variantPreview").classList.add("hidden");
    } catch (error) {
      setStatus(error.message || String(error), "error");
    }
  }
}

async function onStandardFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  await withBusy("標準表情を読み込み中...", async () => {
    setStatus("標準表情を読み込み中...");
    const data = await upload("standard", file);
    state.standardUrl = data.url;
    state.baseUrl = data.url;
    $("standardName").textContent = file.name;
    $("baseName").textContent = "感情画像: 標準表情を使用";
    showImage("standardPreview", data.url);
    showImage("basePreview", data.url);
    setStatus("標準表情を読み込みました", "ok");
  });
}

async function onCharacterFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  await withBusy("キャラクター画像を読み込み中...", async () => {
    setStatus("キャラクター画像を読み込み中...");
    const data = await upload("character", file);
    state.characterUrl = data.url;
    state.generatedStandardUrl = "";
    $("characterName").textContent = file.name;
    $("generatedStandardName").textContent = "生成結果: 未生成";
    $("generatedStandardPreview").classList.add("hidden");
    $("useGeneratedStandard").classList.add("hidden");
    showImage("characterPreview", data.url);
    setStatus("キャラクター画像を読み込みました", "ok");
  });
}

async function onEmotionFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  await withBusy("感情画像を読み込み中...", async () => {
    setStatus("感情画像を読み込み中...");
    const { label } = selectedEmotion();
    const data = await upload("base", file, { emotionLabel: label });
    state.baseUrl = data.url;
    $("baseName").textContent = `感情画像: ${file.name}`;
    showImage("basePreview", data.url);
    setStatus("感情画像を読み込みました", "ok");
  });
}

async function onVariantFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  await withBusy("反対状態の画像を読み込み中...", async () => {
    setStatus("反対状態の画像を読み込み中...");
    const data = await upload("variant", file);
    state.variantUrl = data.url;
    $("variantName").textContent = `反対状態画像: ${file.name}`;
    showImage("variantPreview", data.url);
    setStatus("反対状態の画像を読み込みました", "ok");
  });
}

function appendStandardPreset(text) {
  const input = $("standardExtraPrompt");
  const current = input.value.trim();
  input.value = current ? `${current}\n${text}` : text;
  input.focus();
}

async function generateStandardFace() {
  const { provider, model } = modelParts();
  const key = provider === "openai" ? $("openaiKey").value : $("geminiKey").value;
  $("generateStandardFace").disabled = true;
  try {
    await withBusy("標準表情を生成中...", async () => {
      setStatus("標準表情を生成中...");
      const data = await api("/api/generate-standard-face", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: state.sessionId,
          provider,
          apiKey: key,
          model,
          imageSize: "2K",
          extraPrompt: $("standardExtraPrompt").value,
        }),
      });
      state.generatedStandardUrl = data.url;
      $("generatedStandardName").textContent = `生成結果: ${data.filename}`;
      showImage("generatedStandardPreview", data.url);
      $("useGeneratedStandard").classList.remove("hidden");
      setStatus("標準表情の生成が完了しました", "ok");
    });
  } finally {
    $("generateStandardFace").disabled = false;
  }
}

async function useGeneratedStandard() {
  $("useGeneratedStandard").disabled = true;
  try {
    await withBusy("標準表情として設定中...", async () => {
      const data = await api("/api/use-generated-standard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: state.sessionId }),
      });
      state.standardUrl = data.url;
      state.baseUrl = data.url;
      state.variantUrl = "";
      state.patternsReady = false;
      $("standardName").textContent = `生成標準表情: ${data.filename}`;
      $("baseName").textContent = "感情画像: 標準表情を使用";
      $("variantName").textContent = "反対状態画像: 未選択";
      $("variantPreview").classList.add("hidden");
      $("baseEye").value = "true";
      $("baseMouth").value = "true";
      showImage("standardPreview", data.url);
      showImage("basePreview", data.url);
      switchTab("create");
      setStatus("生成画像を標準表情として設定しました", "ok");
    });
  } finally {
    $("useGeneratedStandard").disabled = false;
  }
}

async function generateEmotion() {
  const { emotion, label } = selectedEmotion();
  if (emotion === "neutral") return;
  const { provider, model } = modelParts();
  const key = provider === "openai" ? $("openaiKey").value : $("geminiKey").value;
  $("generateEmotion").disabled = true;
  try {
    await withBusy(`${label}の画像を生成中...`, async () => {
      setStatus(`${label}の画像を生成中...`);
      const data = await api("/api/generate-emotion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: state.sessionId,
          emotion,
          emotionLabel: label,
          provider,
          apiKey: key,
          model,
          imageSize: "2K",
          colorMatch: $("colorMatch").checked,
          extraPrompt: $("emotionExtraPrompt").value,
        }),
      });
      state.baseUrl = data.url;
      state.variantUrl = "";
      $("baseName").textContent = `感情画像: ${data.filename}`;
      $("variantName").textContent = "反対状態画像: 未選択";
      showImage("basePreview", data.url);
      $("variantPreview").classList.add("hidden");
      setStatus(`${label}の画像生成が完了しました`, "ok");
    });
  } finally {
    $("generateEmotion").disabled = false;
  }
}

async function generateVariant() {
  const { provider, model } = modelParts();
  const key = provider === "openai" ? $("openaiKey").value : $("geminiKey").value;
  $("generateVariant").disabled = true;
  try {
    await withBusy("反対状態の画像を生成中...", async () => {
      setStatus("反対状態の画像を生成中...");
      const data = await api("/api/generate-variant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: state.sessionId,
          provider,
          apiKey: key,
          model,
          imageSize: "2K",
          baseEyeOn: boolValue("baseEye"),
          baseMouthOn: boolValue("baseMouth"),
          extraPrompt: $("variantExtraPrompt").value,
        }),
      });
      state.variantUrl = data.url;
      $("variantName").textContent = `反対状態画像: ${data.filename}`;
      showImage("variantPreview", data.url);
      setStatus("反対状態の画像生成が完了しました", "ok");
    });
  } finally {
    $("generateVariant").disabled = false;
  }
}

async function preparePatterns() {
  $("preparePatterns").disabled = true;
  try {
    await withBusy("4パターンを作成中...", async () => {
      setStatus("4パターンを作成中...");
      const data = await api("/api/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: state.sessionId,
          baseEyeOn: boolValue("baseEye"),
          baseMouthOn: boolValue("baseMouth"),
          colorMatch: $("colorMatch").checked,
          feather: Number($("feather").value),
        }),
      });
      state.baseUrl = data.baseUrl;
      state.variantUrl = data.variantUrl;
      setMaskBackdrops(data.baseUrl, data.variantUrl);
      await loadMask("eyeMask", data.eyeMaskUrl);
      await loadMask("mouthMask", data.mouthMaskUrl);
      updatePatterns(data.patterns);
      state.patternsReady = true;
      switchTab("adjust");
      setStatus(`4パターンを作成しました（位置合わせスコア: ${data.alignmentScore.toFixed(2)}）`, "ok");
    });
  } finally {
    $("preparePatterns").disabled = false;
  }
}

function setMaskBackdrops(baseUrl, variantUrl) {
  [
    ["eyeBaseBackdrop", baseUrl],
    ["mouthBaseBackdrop", baseUrl],
    ["eyeBackdrop", variantUrl],
    ["mouthBackdrop", variantUrl],
  ].forEach(([id, url]) => {
    const img = $(id);
    img.onload = () => {
      if (state.maskFit) fitMaskZoom();
      else applyMaskZoom();
    };
    img.src = cacheBust(url);
  });
  applyBaseOpacity();
}

function setupCanvas(canvasId) {
  const canvas = $(canvasId);
  canvas.width = 320;
  canvas.height = 240;
  canvas.style.aspectRatio = "4 / 3";
  applyMaskZoom();
  canvas.addEventListener("pointerdown", (e) => {
    state.drawing = true;
    state.activeCanvas = canvas;
    canvas.setPointerCapture(e.pointerId);
    drawAt(canvas, e);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (state.drawing && state.activeCanvas === canvas) drawAt(canvas, e);
  });
  canvas.addEventListener("pointerup", () => {
    state.drawing = false;
    state.activeCanvas = null;
  });
  canvas.addEventListener("pointercancel", () => {
    state.drawing = false;
    state.activeCanvas = null;
  });
}

function canvasPoint(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * canvas.width,
    y: ((event.clientY - rect.top) / rect.height) * canvas.height,
  };
}

function drawAt(canvas, event) {
  const ctx = canvas.getContext("2d");
  const p = canvasPoint(canvas, event);
  const size = Number($("brushSize").value);
  ctx.save();
  ctx.beginPath();
  ctx.arc(p.x, p.y, size / 2, 0, Math.PI * 2);
  if (state.paintMode === "erase") {
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,1)";
  } else {
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,1)";
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "rgba(255, 64, 64, 0.72)";
  }
  ctx.fill();
  ctx.restore();
  scheduleRenderPreview();
}

async function loadMask(canvasId, url) {
  const canvas = $(canvasId);
  const ctx = canvas.getContext("2d");
  const img = await loadImage(cacheBust(url));
  canvas.width = img.naturalWidth || img.width;
  canvas.height = img.naturalHeight || img.height;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const off = document.createElement("canvas");
  off.width = canvas.width;
  off.height = canvas.height;
  const octx = off.getContext("2d");
  octx.drawImage(img, 0, 0, off.width, off.height);
  const data = octx.getImageData(0, 0, off.width, off.height);
  for (let i = 0; i < data.data.length; i += 4) {
    const v = data.data[i];
    data.data[i] = 255;
    data.data[i + 1] = 64;
    data.data[i + 2] = 64;
    data.data[i + 3] = v > 32 ? 184 : 0;
  }
  ctx.putImageData(data, 0, 0);
  if (state.maskFit) fitMaskZoom();
  else applyMaskZoom();
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function clearCanvas(id) {
  const canvas = $(id);
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  scheduleRenderPreview();
}

function zoomLabel(value) {
  return `${Math.round(value * 100)}%`;
}

function setElementSize(el, width, height) {
  el.style.width = `${Math.max(1, Math.round(width))}px`;
  el.style.height = `${Math.max(1, Math.round(height))}px`;
}

function applyMaskZoom() {
  [
    ["eyeMask", "eyeBackdrop", "eyeBaseBackdrop"],
    ["mouthMask", "mouthBackdrop", "mouthBaseBackdrop"],
  ].forEach(([canvasId, imageId, baseImageId]) => {
    const canvas = $(canvasId);
    const image = $(imageId);
    const baseImage = $(baseImageId);
    const width = canvas.width || image.naturalWidth || 320;
    const height = canvas.height || image.naturalHeight || 240;
    setElementSize(canvas, width * state.maskZoom, height * state.maskZoom);
    setElementSize(image, width * state.maskZoom, height * state.maskZoom);
    setElementSize(baseImage, width * state.maskZoom, height * state.maskZoom);
  });
  $("maskZoomValue").textContent = zoomLabel(state.maskZoom);
}

function fitMaskZoom() {
  const fits = [["eyeMask", "eyeBackdrop"], ["mouthMask", "mouthBackdrop"]].map(([canvasId, imageId]) => {
    const canvas = $(canvasId);
    const image = $(imageId);
    const wrap = canvas.closest(".canvas-wrap");
    const width = canvas.width || image.naturalWidth || 320;
    const height = canvas.height || image.naturalHeight || 240;
    if (!wrap || width <= 0 || height <= 0) return 1;
    const availableWidth = Math.max(1, wrap.clientWidth - 2);
    const availableHeight = Math.max(1, wrap.clientHeight - 2);
    return Math.min(availableWidth / width, availableHeight / height);
  });
  state.maskFit = true;
  state.maskZoom = clamp(Math.min(...fits), 0.1, 6);
  applyMaskZoom();
}

function changeMaskZoom(delta) {
  state.maskFit = false;
  state.maskZoom = clamp(state.maskZoom + delta, 0.1, 6);
  applyMaskZoom();
}

function applyPreviewZoom() {
  const width = Math.max(160, state.previewBaseWidth * state.previewZoom);
  document.documentElement.style.setProperty("--preview-item-width", `${Math.round(width)}px`);
  $("previewZoomValue").textContent = zoomLabel(state.previewZoom);
}

function fitPreviewZoom() {
  const list = $("previewList");
  const baseWidth = state.previewBaseWidth || 320;
  const availableWidth = Math.max(1, (list.clientWidth - 32) / 2);
  state.previewFit = true;
  state.previewZoom = clamp(availableWidth / baseWidth, 0.1, 6);
  applyPreviewZoom();
}

function changePreviewZoom(delta) {
  state.previewFit = false;
  state.previewZoom = clamp(state.previewZoom + delta, 0.1, 6);
  applyPreviewZoom();
}

function applyBaseOpacity() {
  const opacity = Number($("baseOpacity").value) / 100;
  $("baseOpacityValue").textContent = `${Math.round(opacity * 100)}%`;
  ["eyeBaseBackdrop", "mouthBaseBackdrop"].forEach((id) => {
    $(id).style.opacity = String(opacity);
  });
}

async function renderPreview() {
  if (!state.patternsReady) return;
  if (state.renderRunning) {
    state.renderQueued = true;
    return;
  }

  state.renderRunning = true;
  setPreviewAutoState("反映中...", "running");
  try {
    const data = await api("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: state.sessionId,
        eyeMask: $("eyeMask").toDataURL("image/png"),
        mouthMask: $("mouthMask").toDataURL("image/png"),
        feather: Number($("feather").value),
        baseEyeOn: boolValue("baseEye"),
        baseMouthOn: boolValue("baseMouth"),
      }),
    });
    updatePatterns(data.patterns);
    setStatus("マスク変更をプレビューへ反映しました", "ok");
    setPreviewAutoState("自動反映", "");
  } catch (error) {
    setStatus(error.message || String(error), "error");
    setPreviewAutoState("反映失敗", "error");
  } finally {
    state.renderRunning = false;
    if (state.renderQueued) {
      state.renderQueued = false;
      scheduleRenderPreview(120);
    }
  }
}

function scheduleRenderPreview(delay = 450) {
  if (!state.patternsReady) return;
  window.clearTimeout(state.renderTimer);
  setPreviewAutoState("反映待ち...", "pending");
  state.renderTimer = window.setTimeout(() => {
    renderPreview();
  }, delay);
}

function setPreviewAutoState(text, kind) {
  const el = $("previewAutoState");
  el.textContent = text;
  el.className = `auto-state ${kind || ""}`.trim();
}

function updatePatterns(urls) {
  state.patterns = urls || [];
  const list = $("previewList");
  list.innerHTML = "";
  patternLabels.forEach((label, index) => {
    const item = document.createElement("div");
    item.className = "preview-item";
    const h = document.createElement("h3");
    h.textContent = label;
    item.appendChild(h);
    if (state.patterns[index]) {
      const img = document.createElement("img");
      img.onload = () => {
        if (index === 0 && img.naturalWidth) {
          state.previewBaseWidth = img.naturalWidth;
          if (state.previewFit) fitPreviewZoom();
          else applyPreviewZoom();
        }
      };
      img.src = cacheBust(state.patterns[index]);
      item.appendChild(img);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty";
      item.appendChild(empty);
    }
    list.appendChild(item);
  });
  if (state.previewFit) fitPreviewZoom();
  else applyPreviewZoom();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  $("standardGenTab").classList.toggle("active", name === "standardGen");
  $("createTab").classList.toggle("active", name === "create");
  $("adjustTab").classList.toggle("active", name === "adjust");
}

function updateProviderFields() {
  const { provider } = modelParts();
  $("geminiKeyWrap").classList.toggle("hidden", provider === "openai");
  $("openaiKeyWrap").classList.toggle("hidden", provider !== "openai");
}

function downloadZip() {
  const resize = $("resizeCores3").checked ? "true" : "false";
  window.location.href = `/api/export?sessionId=${encodeURIComponent(state.sessionId)}&resizeCores3=${resize}`;
}

function setupSplitters() {
  const sidebar = document.querySelector(".sidebar");
  const mainSplitter = $("sidebarSplitter");
  const workspace = document.querySelector(".workspace");
  const workspaceSplitter = $("workspaceSplitter");

  bindSplitter(mainSplitter, {
    start: () => sidebar.getBoundingClientRect().width,
    move: (startWidth, deltaX) => {
      const maxWidth = Math.max(320, window.innerWidth - 520);
      const width = clamp(startWidth + deltaX, 280, maxWidth);
      document.documentElement.style.setProperty("--sidebar-width", `${Math.round(width)}px`);
      updateFitZooms();
    },
  });

  bindSplitter(workspaceSplitter, {
    start: () => document.querySelector(".mask-area").getBoundingClientRect().width,
    move: (startWidth, deltaX) => {
      const totalWidth = workspace.getBoundingClientRect().width;
      const width = clamp(startWidth + deltaX, 300, Math.max(300, totalWidth - 306));
      workspace.style.gridTemplateColumns = `${Math.round(width)}px 6px minmax(280px, 1fr)`;
      updateFitZooms();
    },
  });
}

function bindSplitter(splitter, handlers) {
  let startX = 0;
  let startWidth = 0;
  let dragging = false;

  const begin = (clientX) => {
    startX = clientX;
    startWidth = handlers.start();
    dragging = true;
    splitter.classList.add("dragging");
  };
  const move = (clientX) => {
    if (!dragging) return;
    handlers.move(startWidth, clientX - startX);
  };
  const end = () => {
    if (!dragging) return;
    dragging = false;
    splitter.classList.remove("dragging");
    updateFitZooms();
  };
  const onPointerMove = (event) => {
    move(event.clientX);
  };
  const onPointerUp = () => {
    end();
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    window.removeEventListener("pointercancel", onPointerUp);
  };
  const onMouseMove = (event) => {
    move(event.clientX);
  };
  const onMouseUp = () => {
    end();
    window.removeEventListener("mousemove", onMouseMove);
    window.removeEventListener("mouseup", onMouseUp);
  };

  splitter.addEventListener("pointerdown", (event) => {
    begin(event.clientX);
    if (splitter.setPointerCapture && event.pointerId != null) {
      try {
        splitter.setPointerCapture(event.pointerId);
      } catch {}
    }
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
  });
  splitter.addEventListener("mousedown", (event) => {
    if (window.PointerEvent) return;
    begin(event.clientX);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  });
  splitter.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    handlers.move(startWidth, event.clientX - startX);
  });
  splitter.addEventListener("pointerup", (event) => {
    if (splitter.releasePointerCapture && event.pointerId != null) {
      try {
        splitter.releasePointerCapture(event.pointerId);
      } catch {}
    }
    end();
  });
  splitter.addEventListener("pointercancel", () => {
    end();
  });
}

function updateFitZooms() {
  if (state.maskFit) fitMaskZoom();
  if (state.previewFit) fitPreviewZoom();
}

function setupResizeObservers() {
  const observer = new ResizeObserver(() => updateFitZooms());
  document.querySelectorAll(".canvas-wrap, #previewList").forEach((el) => observer.observe(el));
}

function bind() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  $("characterFile").addEventListener("change", wrap(onCharacterFile));
  $("standardFile").addEventListener("change", wrap(onStandardFile));
  $("emotionFile").addEventListener("change", wrap(onEmotionFile));
  $("variantFile").addEventListener("change", wrap(onVariantFile));
  $("emotionSelect").addEventListener("change", wrap(updateEmotionControls));
  $("customEmotionName").addEventListener("input", wrap(updateEmotionControls));
  $("modelSelect").addEventListener("change", updateProviderFields);
  document.querySelectorAll("[data-standard-preset]").forEach((button) => {
    button.addEventListener("click", () => appendStandardPreset(button.dataset.standardPreset));
  });
  $("generateStandardFace").addEventListener("click", wrap(generateStandardFace));
  $("useGeneratedStandard").addEventListener("click", wrap(useGeneratedStandard));
  $("generateEmotion").addEventListener("click", wrap(generateEmotion));
  $("generateVariant").addEventListener("click", wrap(generateVariant));
  $("preparePatterns").addEventListener("click", wrap(preparePatterns));
  $("downloadZip").addEventListener("click", downloadZip);
  $("maskZoomOut").addEventListener("click", () => changeMaskZoom(-0.1));
  $("maskZoomIn").addEventListener("click", () => changeMaskZoom(0.1));
  $("maskZoomFit").addEventListener("click", fitMaskZoom);
  $("previewZoomOut").addEventListener("click", () => changePreviewZoom(-0.1));
  $("previewZoomIn").addEventListener("click", () => changePreviewZoom(0.1));
  $("previewZoomFit").addEventListener("click", fitPreviewZoom);
  $("baseOpacity").addEventListener("input", applyBaseOpacity);
  $("brushSize").addEventListener("input", () => $("brushValue").textContent = $("brushSize").value);
  $("feather").addEventListener("input", () => {
    $("featherValue").textContent = $("feather").value;
    scheduleRenderPreview();
  });
  $("paintMode").addEventListener("click", () => setMode("paint"));
  $("eraseMode").addEventListener("click", () => setMode("erase"));
  $("clearEye").addEventListener("click", () => clearCanvas("eyeMask"));
  $("clearMouth").addEventListener("click", () => clearCanvas("mouthMask"));
  setupCanvas("eyeMask");
  setupCanvas("mouthMask");
  setupSplitters();
  setupResizeObservers();
  applyBaseOpacity();
  fitMaskZoom();
  fitPreviewZoom();
  updateProviderFields();
  updateEmotionControls();
}

function setMode(mode) {
  state.paintMode = mode;
  $("paintMode").classList.toggle("active", mode === "paint");
  $("eraseMode").classList.toggle("active", mode === "erase");
}

function wrap(fn) {
  return async (event) => {
    try {
      await fn(event);
    } catch (error) {
      setStatus(error.message || String(error), "error");
    }
  };
}

bind();
initSession().catch((error) => setStatus(error.message || String(error), "error"));
