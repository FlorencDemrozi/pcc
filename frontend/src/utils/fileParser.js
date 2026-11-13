// ── File parsing utilities ────────────────────────────────────────────────────

import { loadJSZip, loadXLSX } from "./lazyLibs.js";

export function readFileAsBase64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result.split(",")[1]);
    r.onerror = () => rej(new Error("Read failed"));
    r.readAsDataURL(file);
  });
}

export function readFileAsText(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = () => rej(new Error("Read failed"));
    r.readAsText(file);
  });
}

// Third-party parsers are bundled (no runtime CDN loading) and code-split via
// dynamic import() so they are only fetched when a ZIP/XLSX file is opened.

export async function extractZipPDFs(zipFile) {
  const JSZip = await loadJSZip();
  const zip = await JSZip.loadAsync(zipFile);
  const pdfs = [];
  for (const [name, entry] of Object.entries(zip.files)) {
    if (name.toLowerCase().endsWith(".pdf") && !entry.dir) {
      const blob = await entry.async("blob");
      pdfs.push(new File([blob], name, { type: "application/pdf" }));
    }
  }
  return pdfs.sort((a, b) => a.name.localeCompare(b.name));
}

// Detect the delimiter (, ; or TAB) from the header line, ignoring quoted text.
export function detectDelimiter(text) {
  const counts = { ",": 0, ";": 0, "\t": 0 };
  let inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (inQ && text[i + 1] === '"') { i++; continue; }
      inQ = !inQ;
    } else if (!inQ) {
      if (ch === "\n" || ch === "\r") break;
      if (ch in counts) counts[ch]++;
    }
  }
  let best = ",", n = 0;
  for (const d of [",", ";", "\t"]) if (counts[d] > n) { best = d; n = counts[d]; }
  return best;
}

// RFC-4180 state-machine tokenizer: returns an array of records (arrays of strings).
// Handles quoted fields, escaped quotes (""), CR/LF/CRLF line endings and
// newlines/delimiters inside quoted fields.
export function parseCSVRecords(text, delimiter) {
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
  const delim = delimiter || detectDelimiter(text);
  const records = [];
  let row = [], field = "", inQ = false, fieldStarted = false;
  const endField = () => { row.push(field); field = ""; fieldStarted = false; };
  const endRow = () => {
    endField();
    if (!(row.length === 1 && row[0] === "")) records.push(row);   // skip blank lines
    row = [];
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQ = false;
      } else field += ch;
      continue;
    }
    if (ch === '"' && !fieldStarted) { inQ = true; fieldStarted = true; }
    else if (ch === delim) endField();
    else if (ch === "\r") { if (text[i + 1] === "\n") i++; endRow(); }
    else if (ch === "\n") endRow();
    else { field += ch; fieldStarted = true; }
  }
  if (field !== "" || row.length) endRow();
  return records;
}

export function parseCSV(text, delimiter) {
  const records = parseCSVRecords(text, delimiter);
  if (!records.length) return [];
  const headers = records[0].map((h, i) => h.trim() || `column_${i + 1}`);
  return records.slice(1).map(cols => {
    const row = {};
    headers.forEach((h, i) => { row[h] = (cols[i] ?? "").trim(); });
    return row;
  });
}

export async function parseXLSX(file) {
  const XLSX = await loadXLSX();
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws, { defval: "" });
}

// Sanitise rows: replace newlines in all field values with spaces.
// Keyword columns are the exception: EasyChair puts one keyword per line, so
// those newlines become "; " to keep the keywords separate.
export function sanitiseRows(rows) {
  return rows.map(row => {
    const clean = {};
    for (const [k, v] of Object.entries(row)) {
      const isKw = /keyword/i.test(k);
      clean[k] = String(v == null ? "" : v)
        .replace(/\r\n|\r|\n/g, isKw ? "; " : " ")
        .replace(/(;\s*){2,}/g, "; ")
        .trim();
    }
    return clean;
  });
}

// Client-side fallback TXT parser for EasyChair format
export function parseReviewTxtClientSide(text) {
  const rows = [];
  const paperBlocks = text.split(/\*{5,}\s*PAPER\s+(\w+)\s*\*{5,}/);
  let i = 1;
  while (i < paperBlocks.length - 1) {
    const paperId = paperBlocks[i].trim();
    const block   = paperBlocks[i + 1];
    i += 2;
    const titleM   = block.match(/^TITLE:\s*(.+)/m);
    const authorsM = block.match(/^AUTHORS?:\s*(.+)/m);
    const prelim   = block.match(/^PRELIMINARY DECISION:\s*(.+)/im);
    const reviewParts = block.split(/\+{5,}\s*REVIEW\s+\d+\s*\(([^)]+)\)\s*\+{5,}/);
    let j = 1;
    while (j < reviewParts.length - 1) {
      const reviewer = reviewParts[j].trim();
      const section  = reviewParts[j + 1];
      j += 2;
      const scoreM = section.match(/^TOTAL SCORE:\s*([+-]?\d+)/m);
      const confM  = section.match(/^Reviewer'?s?\s+confidence:\s*(\d+)/im);
      const bodyM  = section.match(/----\s*OVERALL EVALUATION\s*----\s*\n([\s\S]*?)(?:----\s*CONFIDENTIAL|$)/i);
      rows.push({
        paper_id:             paperId,
        title:                (titleM?.[1] || "").replace(/\r?\n/g, " ").trim(),
        authors:              (authorsM?.[1] || "").replace(/\r?\n/g, " ").trim(),
        preliminary_decision: (prelim?.[1] || "").trim(),
        reviewer,
        score:      scoreM?.[1] || "",
        confidence: confM?.[1] || "",
        text:       (bodyM?.[1] || section).replace(/\r?\n/g, " ").trim().slice(0, 1000),
      });
    }
  }
  return rows;
}

// Parse any review file — routes TXT to backend, XLSX/CSV handled locally
export async function parseReviewFile(file) {
  const name = file.name.toLowerCase();

  if (name.endsWith(".txt")) {
    const fd = new FormData();
    fd.append("reviews_file", file);
    const r = await fetch("/api/parse/reviews", { method: "POST", body: fd });
    if (!r.ok) {
      const text = await readFileAsText(file);
      return parseReviewTxtClientSide(text);
    }
    return sanitiseRows(await r.json());
  }

  if (name.endsWith(".csv")) {
    const text = await readFileAsText(file);
    return sanitiseRows(parseCSV(text));
  }

  return sanitiseRows(await parseXLSX(file));
}
