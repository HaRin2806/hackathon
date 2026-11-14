/* Sketch2Banner web client — same API contract as the Android app (spec §08).
 * Persistence (spec §10): images in IndexedDB, brief + client_request_id + job_id/token in localStorage,
 * so a reload/closed tab resumes the same job instead of creating a duplicate. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const API = (new URLSearchParams(location.search).get("api") || safeGet("s2b.api") || "").replace(/\/$/, "");
  if (new URLSearchParams(location.search).get("api")) safeSet("s2b.api", API);

  const STYLE_LABEL = { A: "Bám phác thảo", B: "Tối giản", C: "Nhấn ưu đãi" };
  const STAGES = ["QUEUED", "ANALYZING", "VALIDATING", "RENDERING", "SUCCEEDED"];
  const files = { sketch: null, product: null };
  let selectedEvent = null, pollTimer = null, tickTimer = null, startedAt = 0, busy = false;

  // ---------- storage helpers ----------
  function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
  function safeSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} }
  const getJSON = (k) => { try { return JSON.parse(safeGet(k) || "null"); } catch { return null; } };
  const setJSON = (k, v) => safeSet(k, v == null ? null : JSON.stringify(v));

  const idb = (() => {
    let dbp;
    const open = () => dbp || (dbp = new Promise((res, rej) => {
      const r = indexedDB.open("s2b", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("files");
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    }));
    const tx = async (mode, fn) => {
      const db = await open();
      return new Promise((res, rej) => {
        const t = db.transaction("files", mode); const req = fn(t.objectStore("files"));
        t.oncomplete = () => res(req && req.result); t.onerror = () => rej(t.error);
      });
    };
    return {
      put: (k, v) => tx("readwrite", (s) => s.put(v, k)).catch(() => {}),
      get: (k) => tx("readonly", (s) => s.get(k)).catch(() => null),
    };
  })();

  // ---------- image input ----------
  async function downscale(file, maxSide = 2000) {
    // Keeps the photo itself (no crop/redraw); only resizes so uploads stay < 5 MB.
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" }).catch(() => null);
    if (!bmp) return file;
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 3.5e6 && /jpe?g|png|webp/.test(file.type)) return file;
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * scale); c.height = Math.round(bmp.height * scale);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return new Promise((res) => c.toBlob((b) => res(b || file), "image/jpeg", 0.9));
  }

  function bindDrop(role) {
    const drop = $(role === "sketch" ? "#dropSketch" : "#dropProduct");
    const input = drop.querySelector("input");
    const set = async (file) => {
      if (!file || !file.type.startsWith("image/")) return;
      const blob = await downscale(file);
      files[role] = blob; await idb.put(role, blob); show(role, blob); refreshButton();
    };
    input.addEventListener("change", () => set(input.files[0]));
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); set(e.dataTransfer.files[0]); });
  }
  function show(role, blob) {
    const drop = $(role === "sketch" ? "#dropSketch" : "#dropProduct");
    const img = drop.querySelector("img");
    img.src = URL.createObjectURL(blob); img.hidden = false; drop.classList.add("has");
  }

  // ---------- brief ----------
  const form = $("#briefForm");
  function readBrief() {
    const f = new FormData(form);
    return {
      product_name: (f.get("product_name") || "").trim(), headline: (f.get("headline") || "").trim(),
      price: (f.get("price") || "").trim(), cta: (f.get("cta") || "").trim(),
      history_event_id: selectedEvent ? selectedEvent.id : null,
    };
  }
  function saveDraft() { setJSON("s2b.draft", { brief: readBrief(), event: selectedEvent }); }
  form.addEventListener("input", () => { saveDraft(); refreshButton(); });
  function refreshButton() {
    const b = readBrief();
    const ok = files.sketch && files.product && b.product_name && b.cta && !busy;
    $("#btnGenerate").disabled = !ok;
  }

  // ---------- history events ----------
  async function searchEvents(params) {
    const qs = new URLSearchParams({ limit: 30, ...params });
    try {
      const r = await fetch(`${API}/v1/history/events?${qs}`);
      const { items } = await r.json();
      const ul = $("#histList"); ul.innerHTML = "";
      if (!items.length) { ul.innerHTML = `<li class="muted">Không có sự kiện phù hợp.</li>`; return; }
      for (const e of items) {
        const li = document.createElement("li");
        li.innerHTML = `<b>${e.year}</b>${esc(e.event)}<span class="badge ${e.verified ? "v" : "u"}">${e.verified ? "đã kiểm" : "chưa kiểm chứng"}</span>
          <small>${esc(e.summary || "")}</small>`;
        li.onclick = () => selectEvent(e);
        ul.appendChild(li);
      }
    } catch { $("#histList").innerHTML = `<li class="muted">Không tải được danh sách sự kiện.</li>`; }
  }
  function selectEvent(e) {
    selectedEvent = e; saveDraft();
    const box = $("#histSelected");
    if (!e) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<span>Đã gắn: <b>${e.year} · ${esc(e.event)}</b></span><button type="button" class="ghost">Bỏ</button>`;
    box.querySelector("button").onclick = () => selectEvent(null);
  }
  let qTimer;
  $("#histQ").addEventListener("input", (ev) => { clearTimeout(qTimer); qTimer = setTimeout(() => searchEvents({ q: ev.target.value }), 250); });
  $("#histToday").onclick = () => {
    const d = new Date(); const md = `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    $("#histQ").value = ""; searchEvents({ month_day: md });
  };
  $("#historyBox").addEventListener("toggle", (e) => { if (e.target.open && !$("#histList").children.length) searchEvents({}); });

  // ---------- generate ----------
  $("#btnGenerate").onclick = async () => {
    const pending = { client_request_id: uuid(), brief: readBrief(), started: Date.now() };
    setJSON("s2b.pending", pending); // saved BEFORE POST (spec §10 step 2)
    await submit(pending);
  };

  async function submit(pending) {
    setBusy(true); hide("#error"); hide("#results"); showProgress("QUEUED");
    const fd = new FormData();
    fd.append("sketch", files.sketch, "sketch.jpg");
    fd.append("product", files.product, "product.jpg");
    fd.append("brief_json", JSON.stringify(pending.brief));
    fd.append("client_request_id", pending.client_request_id);
    try {
      const r = await fetchTimeout(`${API}/v1/generations`, { method: "POST", body: fd }, 60000);
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw apiError(body, r.status);
      setJSON("s2b.pending", { ...pending, job_id: body.job_id, job_token: body.job_token });
      poll(body.job_id, body.job_token, pending.started);
    } catch (e) {
      fail(e.message || "Không gửi được yêu cầu. Kiểm tra mạng rồi thử lại.", true);
    }
  }

  function poll(jobId, token, started) {
    startedAt = started || Date.now();
    $("#jobShort").textContent = jobId;
    clearInterval(tickTimer);
    tickTimer = setInterval(() => ($("#elapsed").textContent = Math.round((Date.now() - startedAt) / 1000)), 500);
    const once = async () => {
      if (document.hidden) { pollTimer = setTimeout(once, 1500); return; } // stop polling in background
      try {
        const r = await fetchTimeout(`${API}/v1/generations/${jobId}`, { headers: { "X-Job-Token": token } }, 15000);
        const job = await r.json();
        if (!r.ok) throw apiError(job, r.status);
        showProgress(job.stage);
        if (job.status === "SUCCEEDED") return done(job, token);
        if (job.status === "FAILED" || job.status === "INTERRUPTED") {
          setJSON("s2b.pending", null);
          return fail(`${job.error_message || "Tạo thất bại."} (mã: ${job.error_code})`, true);
        }
      } catch (e) { /* transient network error: keep polling */ }
      pollTimer = setTimeout(once, 1000);
    };
    once();
  }

  function done(job, token) {
    clearInterval(tickTimer); setBusy(false); setJSON("s2b.pending", null);
    $("#progress").querySelectorAll("li").forEach((li) => { li.className = "done"; });
    addRecent({ job_id: job.job_id, token, created_at: job.created_at, product: job.brief?.product_name });
    renderResult(job, token, false);
  }

  function renderResult(job, token, isOld) {
    const res = $("#results"); res.hidden = false;
    const tag = $("#resultTag");
    if (job.is_fixture) { tag.className = "chip bad"; tag.textContent = "FIXTURE — không phải AI"; }
    else if (isOld) { tag.className = "chip warn"; tag.textContent = "Kết quả cũ"; }
    else { tag.className = "chip ok"; tag.textContent = "Lượt AI mới"; }

    const headlineNote = job.headline_source === "ai_suggestion" ? ` · Tiêu đề do AI gợi ý: “${esc(job.headline_used)}”` : "";
    $("#reading").innerHTML = `<b>AI đọc phác thảo:</b> ${esc(job.layout_reading || "—")}${headlineNote}`;
    $("#suggestedWarn").hidden = job.layout_source !== "suggested";

    const wrap = $("#variants"); wrap.innerHTML = "";
    for (const v of job.variants) {
      const base = `${API}/v1/generations/${job.job_id}/variants/${v.id}`;
      const el = document.createElement("div"); el.className = "variant";
      el.innerHTML = `<img loading="lazy" alt="Phương án ${v.id}" src="${base}/thumbnail?token=${encodeURIComponent(token)}">
        <div>${v.id} — ${STYLE_LABEL[v.id]}<span>Xem</span></div>`;
      el.onclick = () => openViewer(job, v, `${base}.png?token=${encodeURIComponent(token)}`);
      wrap.appendChild(el);
    }
    const m = job.metrics || {};
    $("#resultMeta").textContent = `job ${job.job_id} · model ${job.model_id} · tạo lúc ${fmtTime(job.created_at)}`
      + (m.total_ms ? ` · server ${(m.total_ms / 1000).toFixed(1)}s (AI ${(m.ai_ms / 1000).toFixed(1)}s, dựng ${(m.render_ms / 1000).toFixed(1)}s)` : "");
    $("#techJson").textContent = JSON.stringify(job, null, 2);
    res.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- viewer / export ----------
  const viewer = $("#viewer");
  async function openViewer(job, v, url) {
    $("#viewerImg").src = url;
    $("#viewerLabel").textContent = `Phương án ${v.id} — ${STYLE_LABEL[v.id]} · 1080×1080`;
    const dl = $("#viewerDownload"); dl.href = url; dl.download = `sketch2banner_${job.job_id}_${v.id}.png`;
    $("#viewerShare").onclick = async () => {
      try {
        const blob = await (await fetch(url)).blob();
        const file = new File([blob], dl.download, { type: "image/png" });
        if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: "Banner" });
        else { dl.click(); }
      } catch {}
    };
    viewer.showModal();
  }
  $("#viewerClose").onclick = () => viewer.close();
  viewer.addEventListener("click", (e) => { if (e.target === viewer) viewer.close(); });

  // ---------- recent ----------
  function addRecent(item) {
    const list = (getJSON("s2b.recent") || []).filter((x) => x.job_id !== item.job_id);
    list.unshift(item); setJSON("s2b.recent", list.slice(0, 6)); renderRecent();
  }
  function renderRecent() {
    const list = getJSON("s2b.recent") || [];
    $("#recentBox").hidden = !list.length;
    const ul = $("#recent"); ul.innerHTML = "";
    for (const it of list) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${esc(it.product || "Banner")} · <code>${it.job_id}</code></span><span class="muted">${fmtTime(it.created_at)}</span>`;
      li.onclick = async () => {
        const r = await fetch(`${API}/v1/generations/${it.job_id}`, { headers: { "X-Job-Token": it.token } });
        if (r.ok) renderResult(await r.json(), it.token, true);
      };
      ul.appendChild(li);
    }
  }

  // ---------- ui helpers ----------
  function showProgress(stage) {
    $("#progress").hidden = false;
    const idx = STAGES.indexOf(stage);
    $("#progress").querySelectorAll("li").forEach((li) => {
      const i = STAGES.indexOf(li.dataset.s);
      li.className = i < idx ? "done" : i === idx ? "active" : "";
    });
  }
  function setBusy(b) { busy = b; $("#btnGenerate").textContent = b ? "Đang tạo…" : "Tạo 3 phương án"; refreshButton(); }
  function fail(msg, keepInput) {
    clearTimeout(pollTimer); clearInterval(tickTimer); setBusy(false);
    const e = $("#error"); e.hidden = false; e.textContent = msg + (keepInput ? " Dữ liệu đã nhập vẫn được giữ." : "");
  }
  const hide = (s) => ($(s).hidden = true);
  function apiError(body, status) {
    const d = body && body.detail;
    const msg = (d && (d.message || (typeof d === "string" ? d : ""))) || `Lỗi server (${status}).`;
    const err = new Error(msg + (d && d.error_code ? ` (mã: ${d.error_code})` : "")); return err;
  }
  function fetchTimeout(url, opts, ms) {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
    return fetch(url, { ...opts, signal: ctl.signal }).finally(() => clearTimeout(t));
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTime = (iso) => { try { return new Date(iso).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }); } catch { return iso || ""; } };
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

  // ---------- boot / restore ----------
  async function health() {
    const chip = $("#health");
    try {
      const h = await (await fetchTimeout(`${API}/health`, {}, 8000)).json();
      const fixture = h.provider === "mock";
      chip.className = "chip " + (fixture ? "bad" : h.ai_key_configured ? "ok" : "warn");
      chip.textContent = fixture ? "FIXTURE (mock)" : `${h.model_id}${h.ai_key_configured ? "" : " · thiếu key"}`;
      $("#fixtureWarn").hidden = !fixture;
    } catch { chip.className = "chip bad"; chip.textContent = "Không kết nối được server"; }
  }

  async function boot() {
    bindDrop("sketch"); bindDrop("product");
    const draft = getJSON("s2b.draft");
    if (draft) {
      for (const [k, v] of Object.entries(draft.brief || {})) if (form.elements[k]) form.elements[k].value = v || "";
      if (draft.event) selectEvent(draft.event);
    }
    for (const role of ["sketch", "product"]) {
      const blob = await idb.get(role);
      if (blob) { files[role] = blob; show(role, blob); }
    }
    refreshButton(); renderRecent(); health();

    // Resume an in-flight generation after reload / closed tab (no duplicate job).
    const pending = getJSON("s2b.pending");
    if (pending) {
      if (pending.job_id) { setBusy(true); showProgress("QUEUED"); poll(pending.job_id, pending.job_token, pending.started); }
      else if (files.sketch && files.product) submit(pending); // same client_request_id -> same job server-side
    }
  }
  boot();
})();
