// ── API helpers ───────────────────────────────────────────────────────────────
// All fetch calls to the backend live here.
// callLLM sends a "task" string (module name) so the backend can pick the
// fast/full model tier configured for that module.

import { safeParseJSON } from "./helpers.js";

// Task names understood by the backend's model-tier selection (Settings uses the same keys).
export const TASKS = {
  screening:     "screening",
  reviewQuality: "review_quality",
  decisions:     "decisions",
  program:       "program",
  email:         "email",
  cfpExtract:    "cfp_extract",
};

// Turn a FastAPI error body ({detail: string | [{msg,...}] | object}) into readable text.
export function formatErrorDetail(body, status) {
  const d = body && body.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (Array.isArray(d) && d.length) {
    return d.map(x => (x && (x.msg || x.message)) ? `${(x.loc || []).slice(1).join(".") || "request"}: ${x.msg || x.message}` : JSON.stringify(x)).join("; ");
  }
  if (d && typeof d === "object") return d.message || JSON.stringify(d);
  if (body && typeof body.error === "string") return body.error;
  return `Server error ${status}`;
}

export async function errorFromResponse(response) {
  let body = null;
  try {
    const txt = await response.text();
    try { body = JSON.parse(txt); } catch { body = txt ? { detail: txt.slice(0, 300) } : null; }
  } catch { /* ignore */ }
  return new Error(formatErrorDetail(body, response.status));
}

// ── Core LLM call ─────────────────────────────────────────────────────────────

/**
 * Call the unified /api/llm endpoint.
 *
 * @param {string}        systemPrompt
 * @param {string|Array}  userContent  - string or Claude-style content block array
 * @param {number}        maxTokens
 * @param {string}        task         - one of TASKS (module name; selects fast/full model)
 * @param {{signal?: AbortSignal}} [opts]
 */
export async function callLLM(systemPrompt, userContent, maxTokens = 1800, task, opts = {}) {
  if (!task) throw new Error("callLLM: task (module name) is required");
  let userText = "";
  let pdfB64   = null;

  if (typeof userContent === "string") {
    userText = userContent;
  } else if (Array.isArray(userContent)) {
    for (const block of userContent) {
      if (block.type === "text") {
        userText += block.text + "\n";
      } else if (block.type === "document" && block.source?.type === "base64") {
        pdfB64 = block.source.data;
      }
    }
    userText = userText.trim();
  }

  const body = { task, system: systemPrompt, user_text: userText, max_tokens: maxTokens };
  if (pdfB64) body.pdf_b64 = pdfB64;
  // "text": backend sends the extracted text (cached from the compliance check)
  // instead of the full PDF — much cheaper, but the model cannot see figures.
  if (pdfB64 && opts.pdfMode) body.pdf_mode = opts.pdfMode;

  let response;
  try {
    response = await fetch("/api/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: opts.signal,
    });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new Error(`Cannot reach the backend (${e?.message || "network error"})`, { cause: e });
  }

  if (!response.ok) throw await errorFromResponse(response);

  const data = await response.json();
  return data.text || "";
}

// Backwards-compat alias used by modules that import "callClaude"
export const callClaude = callLLM;

export const isAbortError = e => e?.name === "AbortError";


// ── Generic backend POST ──────────────────────────────────────────────────────

export async function backendPost(path, formData, opts = {}) {
  const response = await fetch(path, { method: "POST", body: formData, signal: opts.signal });
  if (!response.ok) throw await errorFromResponse(response);
  return response.json();
}


// ── PDF checker ───────────────────────────────────────────────────────────────

export async function checkPDFBackend(fileBlob, filename, conf, cameraReady = false, useLlmBlind = false, skipBlind = false) {
  const fd = new FormData();
  fd.append("file", fileBlob, filename);
  fd.append("max_pages",         String(conf.maxPages || 6));
  fd.append("double_blind",      String(!skipBlind && conf.doubleBlind !== false));
  fd.append("copyright_notices", JSON.stringify(conf.copyrightNotices || []));
  fd.append("camera_ready",      String(cameraReady));
  fd.append("expected_layout",   conf.expectedLayout || "any");
  fd.append("validation_stamp",  conf.validationStamp || "");
  fd.append("use_llm_blind",     String(useLlmBlind && !skipBlind));
  return backendPost("/api/check/pdf", fd);
}

export async function countPagesBackend(fileBlob, filename) {
  const fd = new FormData();
  fd.append("file", fileBlob, filename);
  fd.append("max_pages",         "999");
  fd.append("double_blind",      "false");
  fd.append("copyright_notices", "[]");
  fd.append("camera_ready",      "false");
  fd.append("expected_layout",   "any");
  fd.append("validation_stamp",  "");
  try {
    const r = await fetch("/api/check/pdf", { method: "POST", body: fd });
    if (!r.ok) return null;
    const d = await r.json();
    return d.raw_pages || null;
  } catch { return null; }
}


// ── Conference config ─────────────────────────────────────────────────────────

// Returns the stored conference config object, or null if none/unavailable.
export async function loadConferenceConfig() {
  try {
    const r = await fetch("/api/config/conference");
    if (r.ok) {
      const d = await r.json();
      return d && typeof d === "object" && !Array.isArray(d) ? d : null;
    }
  } catch { /* fall through */ }
  // Fallback: full config contains a "conference" block
  try {
    const r = await fetch("/api/config");
    if (r.ok) {
      const d = await r.json();
      return d && typeof d.conference === "object" ? d.conference : null;
    }
  } catch { /* ignore */ }
  return null;
}

export async function saveConferenceConfig(conf) {
  const r = await fetch("/api/config/conference", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(conf),
  });
  if (!r.ok) throw await errorFromResponse(r);
}


// ── API key ───────────────────────────────────────────────────────────────────

export async function getApiKeyStatus() {
  const r = await fetch("/api/config/apikey");
  if (r.ok) return r.json();
  return { set: false, masked: "" };
}

export async function setApiKey(key) {
  const r = await fetch("/api/config/apikey", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  return r.ok;
}


// ── CFP extraction ────────────────────────────────────────────────────────────

export async function extractFromCFP(pdfBase64, url) {
  const system = `You are an expert conference metadata extractor specialised in reading Call for Papers documents.
Extract ALL structured information especially DEADLINES and CONFERENCE DAYS.

For deadlines, look carefully for:
- Any section titled "Important Dates", "Key Dates", "Deadlines", "Timeline", "Schedule", or similar
- Dates in any format: "January 15, 2026", "15 Jan 2026", "15/01/2026", "01/15/2026", "2026-01-15"
- Labels like "Paper submission", "Abstract deadline", "Full paper", "Notification", "Camera ready", "Registration"
- Convert ALL dates to ISO format YYYY-MM-DD. If year is missing, infer from context.

For conference days:
- Look for the actual conference event dates (not submission deadlines)
- Labels like "Conference dates", "Event dates", "Conference: July 15-17, 2026"
- Extract each individual day as a separate entry with its date
- Default start time 09:00, end time 18:00 unless specified otherwise

Return ONLY a JSON object (no markdown, no explanation):
{
  "name": "", "acronym": "", "edition": "", "year": "", "dates": "",
  "venue": "", "city": "", "country": "", "website": "", "submissionSystem": "",
  "scope": "", "keywords": [], "maxPages": null, "template": "", "doubleBlind": null,
  "deadlines": [{ "label": "Paper submission", "date": "2026-01-15" }],
  "conferenceDays": [{ "date": "2026-07-15", "start": "09:00", "end": "18:00" }],
  "tracks": [{ "name": "", "description": "" }],
  "organizers": [{ "role": "", "name": "", "affiliation": "" }],
  "sponsors": [], "indexing": [], "notes": ""
}
For deadlines: extract EVERY date you find. Dates MUST be YYYY-MM-DD format.
For conferenceDays: one entry per day. Expand date ranges into individual days.
If a field cannot be determined use null for scalars and [] for arrays.`;

  const content = [];
  if (pdfBase64) content.push({ type: "document", source: { type: "base64", media_type: "application/pdf", data: pdfBase64 } });
  content.push({ type: "text", text: `${url ? `URL: ${url}\n\n` : ""}Extract ALL conference metadata especially ALL deadline dates and conference event days. Return only the JSON.` });

  const text = await callLLM(system, content, 2000, TASKS.cfpExtract);
  return safeParseJSON(text);
}
