// ── General helpers ───────────────────────────────────────────────────────────

// Get the first non-empty value for a list of possible key names in a row object
export function getField(row, ...keys) {
  for (const k of keys) {
    const v = row[k] || row[k.toLowerCase()] || row[k.toUpperCase()];
    if (v) return String(v).trim();
  }
  return "";
}

// Column names that may hold the submission ID in a metadata row
export const ID_KEYS = ["#", "id", "paper_id", "submission_id", "Id", "ID"];

export function rowId(row) {
  return String(getField(row || {}, ...ID_KEYS)).trim();
}

// Extract the submission ID from a PDF filename.
// knownIds (optional, Set/array of strings): prefer a number from the filename that
// is a known submission ID (numbers tried last-first); otherwise the last number.
// e.g. "CONF2026_paper_12.pdf" -> "12", "paper_0042.pdf" -> "0042" (or "42" if known)
export function extractPaperId(filename, knownIds) {
  const base = String(filename || "").split(/[\\/]/).pop().replace(/\.pdf$/i, "");
  const nums = base.match(/\d+/g);
  if (!nums) return "";
  if (knownIds) {
    const known = knownIds instanceof Set ? knownIds : new Set([...knownIds].map(String));
    for (let i = nums.length - 1; i >= 0; i--) {
      const n = nums[i];
      if (known.has(n)) return n;
      const stripped = n.replace(/^0+(?=\d)/, "");
      if (known.has(stripped)) return stripped;
    }
  }
  return nums[nums.length - 1];
}

export function knownIdSet(metaRows) {
  return new Set((metaRows || []).map(rowId).filter(Boolean));
}

// Match a PDF filename to a metadata row by paper ID or title
export function matchMeta(filename, metaRows, knownIds) {
  const base = filename.replace(/\.pdf$/i, "").toLowerCase();
  const id = extractPaperId(filename, knownIds || knownIdSet(metaRows));
  if (id) {
    const row = metaRows.find(r => rowId(r) === id);
    if (row) return row;
  }
  return metaRows.find(r => {
    const title = getField(r, "title", "Title").toLowerCase();
    return title && base.includes(title.slice(0, 20));
  }) || {};
}

// Track of the metadata row matching a PDF filename ("" if none)
export function trackForFile(filename, metaRows, knownIds) {
  if (!metaRows?.length) return "";
  const id = extractPaperId(filename, knownIds || knownIdSet(metaRows));
  const row = id ? metaRows.find(r => rowId(r) === id) : null;
  return row ? String(row.Track || row.track || "").trim() : "";
}

// Robust JSON parser — strips markdown fences and attempts to recover truncated output
export function safeParseJSON(raw) {
  let s = raw.replace(/```json|```/g, "").trim();

  try { return JSON.parse(s); } catch (_) {}

  const objMatch = s.match(/\{[\s\S]*\}/);
  const arrMatch = s.match(/\[[\s\S]*\]/);
  const block = objMatch ? objMatch[0] : arrMatch ? arrMatch[0] : null;
  if (block) { try { return JSON.parse(block); } catch (_) {} }

  // Truncation recovery: close open strings and brackets
  let fixed = s;
  let inStr = false;
  for (let i = 0; i < fixed.length; i++) {
    const ch = fixed[i];
    if (ch === "\\") { i++; continue; }
    if (ch === '"') inStr = !inStr;
  }
  if (inStr) fixed += '"';

  const opens = [];
  for (const ch of fixed) {
    if (ch === "{") opens.push("}");
    else if (ch === "[") opens.push("]");
    else if (ch === "}" || ch === "]") opens.pop();
  }
  fixed += opens.reverse().join("");

  try { return JSON.parse(fixed); } catch (e) {
    throw new Error("JSON parse failed: " + e.message + "\nRaw (first 200): " + s.slice(0, 200), { cause: e });
  }
}

// A spreadsheet would treat these as formulas; plain numbers like -3 or +1.5 are fine.
const FORMULA_START = /^[=+\-@\t\r]/;
const PLAIN_NUMBER  = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

function csvCell(v, delim) {
  let s = v == null ? "" : String(v);
  if (FORMULA_START.test(s) && !PLAIN_NUMBER.test(s.trim())) s = "'" + s;
  if (s.includes('"') || s.includes(delim) || /[\r\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
  return s;
}

// Build CSV text for download (formula-injection safe, RFC-4180 quoting)
export function toCSV(rows, delim = ",") {
  if (!rows.length) return "";
  const headers = Object.keys(rows[0]);
  return [
    headers.map(h => csvCell(h, delim)).join(delim),
    ...rows.map(r => headers.map(h => csvCell(r[h] ?? "", delim)).join(delim)),
  ].join("\r\n");
}

// Export an array of row objects to a CSV download (UTF-8 with BOM for Excel)
export function exportCSV(rows, filename) {
  if (!rows.length) return;
  const csv = "﻿" + toCSV(rows);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

// Convert rows to CSV string (no download — used when posting to backend)
export function rowsToCSV(rows) {
  if (!rows.length) return "";
  const h = Object.keys(rows[0]);
  const esc = v => String(v == null ? "" : v).replace(/\r\n|\r|\n/g, " ").replace(/"/g, '""');
  return [h.map(k => `"${esc(k)}"`).join(","), ...rows.map(r => h.map(k => `"${esc(r[k] ?? "")}"`).join(","))].join("\n");
}

// Classify an EasyChair decision string (same rules as backend review_stats):
// "accept" | "reject" | "tentative" ("accept?", "reject?") | "none".
// POSTER, ORAL, SHORT PAPER etc. are acceptance categories.
export function classifyDecision(d) {
  const s = String(d || "").trim();
  if (!s) return "none";
  if (s.endsWith("?") || /borderline|undecided|maybe|tbd|pending/i.test(s)) return "tentative";
  if (/^(accept|accepted|poster|oral|short\s+paper|regular\s+paper|presentation)\b/i.test(s)) return "accept";
  if (/^(reject|rejected|desk[\s-]*reject)/i.test(s)) return "reject";
  return "none";
}
