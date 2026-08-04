// ── API helpers ───────────────────────────────────────────────────────────────
// All fetch calls to the backend live here.
// callLLM accepts a "task" string so the backend can enforce the correct
// feature gate (screening / reviews / decisions / program / emails / config).

import { safeParseJSON } from "./helpers.js";

// ── Core LLM call ─────────────────────────────────────────────────────────────

/**
 * Call the unified /api/llm endpoint.
 *
 * @param {string}        systemPrompt
 * @param {string|Array}  userContent  - string or Claude-style content block array
 * @param {number}        maxTokens
 * @param {string}        task         - "screening"|"reviews"|"decisions"|"program"|"emails"|"config"
 */
export async function callLLM(systemPrompt, userContent, maxTokens = 1800, task = "screening") {
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

  const response = await fetch("/api/llm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `API error ${response.status}`);
  }

  const data = await response.json();
  return data.text || "";
}

// Backwards-compat alias used by modules that import "callClaude"
export const callClaude = callLLM;


// ── Generic backend POST ──────────────────────────────────────────────────────

export async function backendPost(path, formData) {
  const response = await fetch(path, { method: "POST", body: formData });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Error ${response.status}`);
  }
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

export async function loadConferenceConfig() {
  const r = await fetch("/api/config/conference");
  if (r.ok) return r.json();
  return null;
}

export async function saveConferenceConfig(conf) {
  await fetch("/api/config/conference", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(conf),
  });
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

  const text = await callLLM(system, content, 2000, "config");
  return safeParseJSON(text);
}
