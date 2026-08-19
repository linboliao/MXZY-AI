const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  config: null,
  upload: null,
  selectedServer: null,
  serverSlides: new Map(),
  activeJob: null,
  pollTimer: null,
  elapsedTimer: null,
  viewer: null,
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds))) return "Not recorded";
  const total = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`;
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function serverStatusLabel(slide) {
  return {
    ready: `Ready · ${formatDuration(slide.processingSeconds)}`,
    processing: `Processing · ${slide.progress || 0}%`,
    queued: "Queued for precomputation",
    failed: "Precomputation failed",
    outdated: "Outdated · Recompute required",
    not_analyzed: "Not analyzed",
  }[slide.analysisStatus] || slide.analysisStatus;
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(element._timer);
  element._timer = window.setTimeout(() => element.classList.remove("show"), 2800);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* no body */ }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function showStage(stage) {
  ["empty", "progress", "viewer"].forEach((name) => {
    $(`#${name}-state`).classList.toggle("hidden", name !== stage);
  });
}

function statusLabel(job) {
  if (job.source_type === "server" && job.source_current === false) return "Outdated";
  return {
    queued: "Pending",
    running: `${job.progress || 0}%`,
    completed: job.result?.geojson_files?.[0]?.type === "Malignant" ? "Suspected Malignancy" : "Completed",
    failed: "Failed",
  }[job.status] || job.status;
}

async function loadJobs() {
  try {
    const { jobs } = await api("/api/jobs");
    const list = $("#job-list");
    if (!jobs.length) {
      list.innerHTML = '<p class="empty-hint">No diagnosis history</p>';
      return;
    }
    list.innerHTML = jobs.map((job) => {
      const date = new Date(job.created_at);
      return `
        <button class="job-item ${state.activeJob?.id === job.id ? "active" : ""}" data-job="${job.id}">
          <span class="job-indicator ${job.status}"></span>
          <span class="job-copy"><strong>${escapeHtml(job.original_name)}</strong><span>${statusLabel(job)}</span></span>
          <span class="job-time">${date.toLocaleDateString("en-US", { month: "2-digit", day: "2-digit" })}</span>
        </button>`;
    }).join("");
    $$(".job-item").forEach((button) => button.addEventListener("click", () => openJob(button.dataset.job)));
  } catch (error) {
    toast(error.message);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

function setUpload(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".svs")) {
    toast("Only SVS files are supported");
    return;
  }
  state.upload = file;
  $("#selected-upload").textContent = `${file.name} · ${formatBytes(file.size)}`;
  $("#selected-upload").classList.remove("hidden");
  $("#upload-button").disabled = false;
}

async function createUploadJob() {
  if (!state.upload) return;
  const button = $("#upload-button");
  button.disabled = true;
  button.textContent = "Uploading…";
  const body = new FormData();
  body.append("slide", state.upload);
  try {
    const { job } = await api("/api/jobs", { method: "POST", body });
    await displayJob(job);
    await loadJobs();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Start Diagnosis";
  }
}

async function loadServerSlides() {
  const list = $("#server-slides");
  state.selectedServer = null;
  state.serverSlides = new Map();
  $("#server-button").disabled = true;
  $("#server-button").textContent = "Awaiting Precomputation";
  list.innerHTML = '<p class="empty-hint">Loading slide library…</p>';
  try {
    const { slides } = await api("/api/server-slides");
    if (!slides.length) {
      list.innerHTML = '<p class="empty-hint">No SVS files are available in the slide library</p>';
      return;
    }
    state.serverSlides = new Map(slides.map((slide) => [slide.id, slide]));
    list.innerHTML = slides.map((slide) => `
      <button class="server-slide ${slide.analysisStatus}" data-slide="${slide.id}">
        <strong>${escapeHtml(slide.name)}</strong>
        <span class="server-meta">${escapeHtml(slide.folder)} · ${formatBytes(slide.size)}</span>
        <span class="server-analysis ${slide.analysisStatus}">${escapeHtml(serverStatusLabel(slide))}</span>
      </button>`).join("");
    $$(".server-slide").forEach((button) => button.addEventListener("click", async () => {
      $$(".server-slide").forEach((item) => item.classList.remove("selected"));
      button.classList.add("selected");
      state.selectedServer = state.serverSlides.get(button.dataset.slide);
      const action = $("#server-button");
      if (state.selectedServer.jobId) {
        action.disabled = false;
        action.textContent = state.selectedServer.analysisStatus === "ready"
          ? "Open Saved Result"
          : "View Analysis Status";
        await openJob(state.selectedServer.jobId);
      } else {
        action.disabled = true;
        action.textContent = state.selectedServer.analysisStatus === "outdated"
          ? "Recompute Required"
          : "Awaiting Precomputation";
      }
    }));
  } catch (error) {
    list.innerHTML = `<p class="empty-hint">${escapeHtml(error.message)}</p>`;
  }
}

async function openSelectedServerJob() {
  if (!state.selectedServer) return;
  if (!state.selectedServer.jobId) return;
  await openJob(state.selectedServer.jobId);
}

async function openJob(jobId) {
  try {
    const { job } = await api(`/api/jobs/${jobId}`);
    await displayJob(job);
    await loadJobs();
  } catch (error) {
    toast(error.message);
  }
}

async function displayJob(job) {
  state.activeJob = job;
  window.clearTimeout(state.pollTimer);
  window.clearInterval(state.elapsedTimer);
  if (job.status === "queued" || job.status === "running") {
    showStage("progress");
    $("#progress-title").textContent = job.message || "Processing Diagnosis";
    $("#progress-filename").textContent = job.original_name;
    $("#progress-percent").textContent = `${job.progress || 0}%`;
    $("#progress-bar").style.width = `${job.progress || 0}%`;
    updateProgressElapsed(job);
    state.elapsedTimer = window.setInterval(() => updateProgressElapsed(job), 1000);
    showEmptyResult();
    state.pollTimer = window.setTimeout(() => pollJob(job.id), 1800);
    return;
  }
  if (job.status === "failed") {
    showStage("progress");
    $("#progress-title").textContent = "Diagnosis Incomplete";
    $("#progress-filename").textContent = job.error || "See server logs for details";
    $("#progress-percent").textContent = "Failed";
    $("#progress-bar").style.width = `${job.progress || 0}%`;
    $("#progress-elapsed").textContent = `Processing time: ${formatDuration(job.processing_seconds)}`;
    showEmptyResult();
    return;
  }
  if (job.status === "completed" && job.source_type === "server" && job.source_current === false) {
    showStage("progress");
    $("#progress-title").textContent = "Saved Result Outdated";
    $("#progress-filename").textContent = "The server slide changed after this result was generated";
    $("#progress-percent").textContent = "Outdated";
    $("#progress-bar").style.width = "0%";
    $("#progress-elapsed").textContent = `Previous processing time: ${formatDuration(job.processing_seconds)}`;
    showEmptyResult();
    return;
  }
  if (job.status === "completed") {
    showStage("viewer");
    renderResult(job);
    await loadViewer(job);
  }
}

async function pollJob(jobId) {
  try {
    const { job } = await api(`/api/jobs/${jobId}`);
    await displayJob(job);
    await loadJobs();
    if (job.source_type === "server" && ["completed", "failed"].includes(job.status)) {
      await loadServerSlides();
    }
  } catch (error) {
    toast(error.message);
  }
}

function updateProgressElapsed(job) {
  const reference = job.started_at || job.created_at;
  const started = Date.parse(reference);
  const seconds = Number.isFinite(started) ? (Date.now() - started) / 1000 : job.processing_seconds;
  const label = job.started_at ? "Processing time" : "Queued time";
  $("#progress-elapsed").textContent = `${label}: ${formatDuration(seconds)}`;
}

function showEmptyResult() {
  $("#result-empty").classList.remove("hidden");
  $("#result-content").classList.add("hidden");
}

function renderResult(job) {
  const result = job.result?.geojson_files?.[0] || {};
  const malignant = result.type === "Malignant";
  $("#result-empty").classList.add("hidden");
  $("#result-content").classList.remove("hidden");
  $("#diagnosis-card").classList.toggle("malignant", malignant);
  $("#diagnosis-type").textContent = malignant ? "Suspected Prostate Cancer" : "No Clear Evidence of Malignancy";
  const confidence = result.conf === "strong" ? "Model agreement: High" : result.conf === "weak" ? "Model agreement: Moderate" : "Model agreement: Not available";
  $("#diagnosis-confidence").textContent = confidence;
  $("#gleason-value").textContent = normalizeMetric(result.Gleason);
  $("#isup-value").textContent = normalizeMetric(result.ISUP);
  $("#area-value").textContent = formatArea(result.percentage);
  $("#download-overlay").href = `/api/jobs/${job.id}/slide/overlay`;
  $("#result-origin").textContent = job.source_type === "server" ? "Precomputed Server Result" : "Uploaded Slide Result";
  $("#result-duration").textContent = `Processing time: ${formatDuration(job.processing_seconds)}`;
  $("#result-completed").textContent = job.completed_at
    ? `Completed ${new Date(job.completed_at).toLocaleString("en-US")}`
    : "Completion time not recorded";
}

function normalizeMetric(value) {
  if (value === undefined || value === null || value === "N/A") return "—";
  return value;
}

function formatArea(value) {
  if (value === undefined || value === null || value === "N/A") return "—";
  const text = String(value).trim();
  const hasPercentSuffix = text.endsWith("%");
  const numeric = Number(hasPercentSuffix ? text.slice(0, -1) : text);
  if (!Number.isFinite(numeric)) return value;
  if (!hasPercentSuffix && numeric >= 0 && numeric <= 1) return `${(numeric * 100).toFixed(0)}%`;
  return `${numeric.toFixed(0)}%`;
}

async function loadViewer(job) {
  if (state.viewer) state.viewer.destroy();
  try {
    const [metadata, overlay] = await Promise.all([
      api(`/api/jobs/${job.id}/slide/metadata`),
      api(`/api/jobs/${job.id}/slide/overlay`),
    ]);
    $("#viewer-filename").textContent = job.original_name;
    const objective = metadata.properties.objectivePower ? ` · ${metadata.properties.objectivePower}×` : "";
    $("#viewer-dimensions").textContent = `${metadata.width.toLocaleString()} × ${metadata.height.toLocaleString()} px${objective}`;
    state.viewer = new DeepZoomCanvas($("#slide-canvas"), metadata, overlay);
  } catch (error) {
    toast(error.message);
  }
}

class DeepZoomCanvas {
  constructor(canvas, metadata, overlay) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.metadata = metadata;
    this.overlay = overlay;
    this.imageCache = new Map();
    this.pending = new Set();
    this.overlayVisible = true;
    this.centerX = metadata.width / 2;
    this.centerY = metadata.height / 2;
    this.scale = 1;
    this.fitScale = 1;
    this.drag = null;
    this.destroyed = false;
    this.resizeObserver = new ResizeObserver(() => this.resize(true));
    this.resizeObserver.observe(canvas.parentElement);
    this.bind();
    this.resize(true);
  }

  bind() {
    this.onWheel = (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0014);
      this.zoomAt(factor, event.offsetX, event.offsetY);
    };
    this.onPointerDown = (event) => {
      this.drag = { x: event.clientX, y: event.clientY, centerX: this.centerX, centerY: this.centerY };
      this.canvas.setPointerCapture(event.pointerId);
      this.canvas.classList.add("dragging");
    };
    this.onPointerMove = (event) => {
      if (!this.drag) return;
      this.centerX = this.drag.centerX - (event.clientX - this.drag.x) / this.scale;
      this.centerY = this.drag.centerY - (event.clientY - this.drag.y) / this.scale;
      this.constrain();
      this.render();
    };
    this.onPointerUp = () => {
      this.drag = null;
      this.canvas.classList.remove("dragging");
    };
    this.onDoubleClick = (event) => this.zoomAt(1.8, event.offsetX, event.offsetY);
    this.canvas.addEventListener("wheel", this.onWheel, { passive: false });
    this.canvas.addEventListener("pointerdown", this.onPointerDown);
    this.canvas.addEventListener("pointermove", this.onPointerMove);
    this.canvas.addEventListener("pointerup", this.onPointerUp);
    this.canvas.addEventListener("pointercancel", this.onPointerUp);
    this.canvas.addEventListener("dblclick", this.onDoubleClick);
  }

  destroy() {
    this.destroyed = true;
    this.resizeObserver.disconnect();
    this.canvas.replaceWith(this.canvas.cloneNode(true));
  }

  resize(reset = false) {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.width * dpr);
    this.canvas.height = Math.round(this.height * dpr);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    this.context.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.fitScale = Math.min(this.width / this.metadata.width, this.height / this.metadata.height) * 0.96;
    if (reset) this.reset();
    else this.render();
  }

  reset() {
    this.centerX = this.metadata.width / 2;
    this.centerY = this.metadata.height / 2;
    this.scale = this.fitScale;
    this.render();
  }

  zoom(factor) {
    this.zoomAt(factor, this.width / 2, this.height / 2);
  }

  zoomAt(factor, screenX, screenY) {
    const beforeX = this.centerX + (screenX - this.width / 2) / this.scale;
    const beforeY = this.centerY + (screenY - this.height / 2) / this.scale;
    this.scale = Math.max(this.fitScale * 0.5, Math.min(8, this.scale * factor));
    this.centerX = beforeX - (screenX - this.width / 2) / this.scale;
    this.centerY = beforeY - (screenY - this.height / 2) / this.scale;
    this.constrain();
    this.render();
  }

  constrain() {
    const halfWidth = this.width / (2 * this.scale);
    const halfHeight = this.height / (2 * this.scale);
    if (halfWidth < this.metadata.width / 2) {
      this.centerX = Math.max(halfWidth, Math.min(this.metadata.width - halfWidth, this.centerX));
    } else {
      this.centerX = this.metadata.width / 2;
    }
    if (halfHeight < this.metadata.height / 2) {
      this.centerY = Math.max(halfHeight, Math.min(this.metadata.height - halfHeight, this.centerY));
    } else {
      this.centerY = this.metadata.height / 2;
    }
  }

  chooseLevel() {
    const ideal = this.metadata.maxLevel + Math.log2(this.scale);
    return Math.max(0, Math.min(this.metadata.maxLevel, Math.round(ideal)));
  }

  render() {
    if (this.destroyed) return;
    const ctx = this.context;
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.fillStyle = "#050807";
    ctx.fillRect(0, 0, this.width, this.height);

    const level = this.chooseLevel();
    const levelInfo = this.metadata.levels[level];
    const levelScale = 2 ** (level - this.metadata.maxLevel);
    const tileSize = this.metadata.tileSize;
    const leftFull = this.centerX - this.width / (2 * this.scale);
    const topFull = this.centerY - this.height / (2 * this.scale);
    const rightFull = this.centerX + this.width / (2 * this.scale);
    const bottomFull = this.centerY + this.height / (2 * this.scale);
    const startCol = Math.max(0, Math.floor(leftFull * levelScale / tileSize) - 1);
    const endCol = Math.min(levelInfo.tilesX - 1, Math.floor(rightFull * levelScale / tileSize) + 1);
    const startRow = Math.max(0, Math.floor(topFull * levelScale / tileSize) - 1);
    const endRow = Math.min(levelInfo.tilesY - 1, Math.floor(bottomFull * levelScale / tileSize) + 1);

    for (let row = startRow; row <= endRow; row += 1) {
      for (let col = startCol; col <= endCol; col += 1) {
        this.drawTile(level, levelScale, col, row);
      }
    }
    if (this.overlayVisible) this.drawOverlay();
    $("#zoom-readout").textContent = `${(this.scale / this.fitScale).toFixed(1)}×`;
  }

  drawTile(level, levelScale, col, row) {
    const key = `${level}/${col}_${row}`;
    const image = this.imageCache.get(key);
    if (!image) {
      this.requestTile(key, level, col, row);
      return;
    }
    const overlap = this.metadata.overlap;
    const levelX = col * this.metadata.tileSize - (col > 0 ? overlap : 0);
    const levelY = row * this.metadata.tileSize - (row > 0 ? overlap : 0);
    const fullX = levelX / levelScale;
    const fullY = levelY / levelScale;
    const x = (fullX - this.centerX) * this.scale + this.width / 2;
    const y = (fullY - this.centerY) * this.scale + this.height / 2;
    const width = image.width / levelScale * this.scale;
    const height = image.height / levelScale * this.scale;
    this.context.drawImage(image, x, y, width + 0.5, height + 0.5);
  }

  requestTile(key, level, col, row) {
    if (this.pending.has(key)) return;
    this.pending.add(key);
    const image = new Image();
    image.onload = () => {
      this.pending.delete(key);
      this.imageCache.set(key, image);
      if (this.imageCache.size > 420) this.imageCache.delete(this.imageCache.keys().next().value);
      this.render();
    };
    image.onerror = () => this.pending.delete(key);
    image.src = this.metadata.tileUrlTemplate
      .replace("{level}", level)
      .replace("{col}", col)
      .replace("{row}", row);
  }

  drawOverlay() {
    const features = this.overlay?.features || [];
    const ctx = this.context;
    ctx.save();
    ctx.fillStyle = "rgba(255, 61, 82, 0.24)";
    ctx.strokeStyle = "rgba(255, 82, 98, 0.95)";
    ctx.lineWidth = 1.4;
    for (const feature of features) {
      const geometry = feature.geometry || {};
      if (geometry.type === "Polygon") this.drawPolygon(geometry.coordinates);
      if (geometry.type === "MultiPolygon") geometry.coordinates.forEach((polygon) => this.drawPolygon(polygon));
    }
    ctx.restore();
  }

  drawPolygon(rings) {
    const ctx = this.context;
    ctx.beginPath();
    for (const ring of rings) {
      ring.forEach(([fullX, fullY], index) => {
        const x = (fullX - this.centerX) * this.scale + this.width / 2;
        const y = (fullY - this.centerY) * this.scale + this.height / 2;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
    }
    ctx.fill("evenodd");
    ctx.stroke();
  }

  toggleOverlay() {
    this.overlayVisible = !this.overlayVisible;
    this.render();
    return this.overlayVisible;
  }
}

function bindEvents() {
  $$(".source-tab").forEach((tab) => tab.addEventListener("click", () => {
    $$(".source-tab").forEach((item) => {
      const active = item === tab;
      item.classList.toggle("active", active);
      item.setAttribute("aria-selected", String(active));
    });
    $$(".source-panel").forEach((panel) => panel.classList.remove("active"));
    $(`#${tab.dataset.tab}-panel`).classList.add("active");
    if (tab.dataset.tab === "server") loadServerSlides();
  }));

  $("#slide-input").addEventListener("change", (event) => setUpload(event.target.files[0]));
  const dropZone = $("#drop-zone");
  ["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  }));
  dropZone.addEventListener("drop", (event) => setUpload(event.dataTransfer.files[0]));
  $("#upload-button").addEventListener("click", createUploadJob);
  $("#server-button").addEventListener("click", openSelectedServerJob);
  $("#refresh-server").addEventListener("click", loadServerSlides);
  $("#refresh-jobs").addEventListener("click", loadJobs);
  $("#zoom-in").addEventListener("click", () => state.viewer?.zoom(1.5));
  $("#zoom-out").addEventListener("click", () => state.viewer?.zoom(1 / 1.5));
  $("#zoom-reset").addEventListener("click", () => state.viewer?.reset());
  $("#toggle-overlay").addEventListener("click", (event) => {
    const visible = state.viewer?.toggleOverlay();
    event.currentTarget.classList.toggle("active", visible);
  });
}

async function initialize() {
  bindEvents();
  setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }); }, 1000);
  try {
    state.config = await api("/api/config");
    $("#file-limit").textContent = `Maximum file size: ${formatBytes(state.config.maxUploadBytes)}`;
  } catch (error) {
    toast(error.message);
  }
  await loadJobs();
}

initialize();
