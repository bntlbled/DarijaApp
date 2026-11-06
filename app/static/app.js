const $ = (s) => document.querySelector(s);
let audioBlob = null, audioName = "recording.webm", result = null, recorder = null, recTimer = null;

// ---------- setup status ----------
fetch("/api/status").then(r => r.json()).then(s => {
  const asr = s.asr_backends.length ? `<b>${s.asr_backends.join(", ")}</b>` : `<span class="warn">none configured</span>`;
  const cl = s.claude ? "<b>connected</b>" : `<span class="warn">no API key</span>`;
  $("#status").innerHTML = `Speech engine: ${asr} · Claude: ${cl}`;
  for (const b of s.asr_backends) $("#backend").insertAdjacentHTML("beforeend", `<option value="${b}">${b}</option>`);
  if (!s.instagram) $("#igAcct").textContent = "Instagram isn't connected yet (see README). Pasted links and your reel list need it.";
}).catch(() => $("#status").textContent = "Server not reachable.");

// ---------- tabs ----------
document.querySelectorAll(".tab[data-tab]").forEach(t => t.onclick = () => {
  document.querySelectorAll(".tab[data-tab]").forEach(x => x.classList.toggle("active", x === t));
  document.querySelectorAll(".pane").forEach(p => p.hidden = p.dataset.pane !== t.dataset.tab);
});

// ---------- audio in ----------
function setAudio(blob, name) {
  audioBlob = blob; audioName = name;
  const p = $("#player"); p.src = URL.createObjectURL(blob); p.hidden = false;
  $("#goAudio").disabled = false;
}
$("#fileIn").onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("#fileLabel").textContent = f.name; setAudio(f, f.name);
};
$("#recBtn").onclick = async () => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { return showError("Microphone access was blocked. Allow it in the browser, or upload a file instead."); }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    stream.getTracks().forEach(t => t.stop()); clearInterval(recTimer);
    $("#recBtn").classList.remove("recording"); $("#recLabel").textContent = "Record again";
    const type = recorder.mimeType || "audio/webm";
    setAudio(new Blob(chunks, { type }), "recording." + (type.includes("mp4") ? "m4a" : "webm"));
  };
  recorder.start();
  const t0 = Date.now();
  $("#recBtn").classList.add("recording"); $("#recLabel").textContent = "Stop";
  recTimer = setInterval(() => $("#recTime").textContent = fmt((Date.now() - t0) / 1000), 250);
};

$("#goAudio").onclick = () => {
  const fd = new FormData();
  fd.append("file", audioBlob, audioName);
  fd.append("backend", $("#backend").value);
  fd.append("context", $("#ctxAudio").value);
  fd.append("language", $("#language").value);
  run(fetch("/api/transcribe", { method: "POST", body: fd }), "Recognising speech, then transliterating and translating…");
};
// ---------- Instagram ----------
function selectTab(name) { document.querySelector(`.tab[data-tab="${name}"]`).click(); }
function igRun(body) {
  audioName = body.media_id ? `reel-${body.media_id}` : "instagram-reel";
  run(fetch("/api/instagram/transcribe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, backend: $("#backend").value, language: $("#language").value, context: $("#ctxAudio").value }),
  }), "Fetching the reel, pulling out the audio, then transcribing…");
}
$("#goIgUrl").onclick = () => {
  const url = $("#igUrl").value.trim();
  if (!url) return showError("Paste a reel link first.");
  igRun({ url });
};
$("#igLoad").onclick = async () => {
  $("#error").hidden = true;
  try {
    const r = await fetch("/api/instagram/media"); const js = await r.json();
    if (!r.ok) throw new Error(js.detail || r.statusText);
    $("#igAcct").textContent = `@${js.account.username} · ${js.videos.length} videos`;
    $("#igList").innerHTML = js.videos.map(v => `<li>
      <button class="igitem" data-id="${esc(v.id)}" ${v.has_video_url ? "" : "disabled title=\"Instagram withholds this video (licensed music). Download it and upload the file.\""}>
        ${v.thumbnail ? `<img src="${esc(v.thumbnail)}" alt="" loading="lazy">` : `<span class="nothumb">▶</span>`}
        <span class="cap">${esc(v.caption || "(no caption)")}</span>
        <span class="muted small">${esc((v.timestamp || "").slice(0, 10))}${v.has_video_url ? "" : " · music-locked"}</span>
      </button></li>`).join("") || "<li class=muted>No videos on this account.</li>";
  } catch (e) { showError(e.message); }
};
$("#igList").onclick = (e) => { const b = e.target.closest(".igitem"); if (b && !b.disabled) igRun({ media_id: b.dataset.id }); };

// Arriving from the Android share sheet.
(async () => {
  const q = new URLSearchParams(location.search);
  history.replaceState(null, "", "/");
  if (q.get("shared")) {
    try {
      const r = await fetch(`/api/shared/${encodeURIComponent(q.get("shared"))}`);
      if (!r.ok) throw new Error((await r.json()).detail);
      const name = "shared" + q.get("shared").replace(/^[0-9a-f]+/, "");
      setAudio(await r.blob(), name); $("#fileLabel").textContent = "Shared video";
      selectTab("audio");
    } catch (e) { showError(e.message || "Couldn't open the shared file."); }
  } else if (q.get("ig")) {
    selectTab("ig"); $("#igUrl").value = q.get("ig");
    const st = await fetch("/api/status").then(r => r.json()).catch(() => ({}));
    if (!st.instagram) showError("You shared a link. Apps can't download other people's reels from a link; share the video file itself (download or screen-record it first).");
  } else if (q.get("share_error")) showError("That file was too large (100 MB max).");
})();

$("#goText").onclick = () => {
  run(fetch("/api/process-text", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: $("#textIn").value, context: $("#ctxText").value }),
  }), "Transliterating and translating…");
};
$("#demoBtn").onclick = () => run(fetch("/api/demo"), "Loading demo…");

async function run(req, msg) {
  $("#error").hidden = true; $("#busy").hidden = false; $("#busyMsg").textContent = msg;
  try {
    const r = await req;
    const js = await r.json();
    if (!r.ok) throw new Error(js.detail || r.statusText);
    result = js; render(js);
  } catch (e) { showError(e.message); }
  finally { $("#busy").hidden = true; }
}
function showError(m) { const e = $("#error"); e.textContent = m; e.hidden = false; }

// ---------- render ----------
const FLAG = { moroccan: "🇲🇦", algerian: "🇩🇿", mixed: "🇲🇦🇩🇿", unknown: "❔" };
const NAME = { moroccan: "Moroccan Darija", algerian: "Algerian Darija", mixed: "Mixed / both", unknown: "Not sure" };
const PILL = { moroccan: "MA", algerian: "DZ", mixed: "MA/DZ", unknown: "?" };
const LANGN = { darija: "Darija", fr: "French", en: "English", msa: "MSA", other: "" };
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function fmt(sec) { sec = Math.floor(sec || 0); const m = Math.floor(sec / 60), s = sec % 60; return `${m}:${String(s).padStart(2, "0")}`; }

function render(r) {
  const d = r.dialect;
  $("#results").hidden = false;
  $("#vFlag").textContent = FLAG[d.label];
  $("#vLabel").textContent = NAME[d.label] + (r.demo ? " · demo" : "");
  $("#vConf").textContent = `${Math.round(d.confidence * 100)}% confidence · lines: ` +
    Object.entries(d.line_votes).map(([k, v]) => `${v} ${PILL[k]}`).join(", ");
  const m = d.markers, tot = m.moroccan + m.algerian;
  $("#barMa").style.width = tot ? `${(100 * m.moroccan) / tot}%` : "50%";
  $("#vWhy").textContent = d.reasoning || "";
  $("#cues").innerHTML = d.markers.top_cues.map(c => {
    const cls = c.includes("moroccan") ? "moroccan" : "algerian";
    return `<span class="chip ${cls}">${esc(c.replace(/ \((moroccan|algerian)\)/, ""))}</span>`;
  }).join("");
  $("#langs").innerHTML = Object.entries(r.languages).filter(([k]) => k !== "other").map(([k, v]) =>
    `<div class="${k}" style="width:${v * 100}%">${v > 0.06 ? `${LANGN[k]} ${Math.round(v * 100)}%` : ""}</div>`).join("");
  drawLines();
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function drawLines() {
  const showSrc = $("#showSrc").checked, showCues = $("#showCues").checked;
  $("#lines").innerHTML = result.lines.map(l => {
    const toks = l.tokens.map(t => t.lang === "darija" || t.lang === "other"
      ? esc(t.t) : `<span class="tok ${t.lang}" title="${LANGN[t.lang]}">${esc(t.t)}</span>`).join(" ");
    return `<li class="line">
      <span class="ts" data-t="${l.start}">${fmt(l.start)}</span>
      <div class="arabizi">${toks}</div>
      <div class="side"><span class="pill ${l.dialect}" title="${Math.round(l.confidence * 100)}%">${PILL[l.dialect]}</span>
        ${l.unclear ? '<span class="unclear">unclear</span>' : ""}</div>
      <div class="english">${esc(l.english)}</div>
      ${showSrc && l.source ? `<div class="src">${esc(l.source)}</div>` : ""}
      ${showCues && l.cues.length ? `<div class="lcues">cues: ${esc(l.cues.join(", "))}</div>` : ""}
    </li>`;
  }).join("");
}
$("#showSrc").onchange = drawLines; $("#showCues").onchange = drawLines;
$("#lines").onclick = (e) => {
  const t = e.target.closest(".ts"); const p = $("#player");
  if (t && !p.hidden) { p.currentTime = +t.dataset.t; p.play(); }
};

// ---------- export ----------
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click();
}
$("#dlJson").onclick = () => download("transcript.json", JSON.stringify(result, null, 1), "application/json");
$("#dlMd").onclick = async () => {
  const r = await fetch("/api/export.md", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result, title: audioName.replace(/\.[^.]+$/, "") || "Transcript" }) });
  download("transcript.md", await r.text(), "text/markdown");
};

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
