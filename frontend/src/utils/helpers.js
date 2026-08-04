// ── General helpers ───────────────────────────────────────────────────────────

// Get the first non-empty value for a list of possible key names in a row object
export function getField(row, ...keys) {
  for (const k of keys) {
    const v = row[k] || row[k.toLowerCase()] || row[k.toUpperCase()];
    if (v) return String(v).trim();
  }
  return "";
}

// Match a PDF filename to a metadata row by paper ID or title
export function matchMeta(filename, metaRows) {
  const base = filename.replace(/\.pdf$/i, "").toLowerCase();
  const numMatch = base.match(/\d+/);
  if (numMatch) {
    const id = numMatch[0];
    const row = metaRows.find(r =>
      String(getField(r, "#", "id", "paper_id", "submission_id", "Id", "ID")).trim() === id
    );
    if (row) return row;
  }
  return metaRows.find(r => {
    const title = getField(r, "title", "Title").toLowerCase();
    return title && base.includes(title.slice(0, 20));
  }) || {};
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
    throw new Error("JSON parse failed: " + e.message + "\nRaw (first 200): " + s.slice(0, 200));
  }
}

// Export an array of row objects to a CSV download
export function exportCSV(rows, filename) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const csv = [
    headers.join(","),
    ...rows.map(r =>
      headers.map(h => `"${String(r[h] || "").replace(/"/g, '""')}"`).join(",")
    ),
  ].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = filename;
  a.click();
}

// Convert rows to CSV string (no download — used when posting to backend)
export function rowsToCSV(rows) {
  if (!rows.length) return "";
  const h = Object.keys(rows[0]);
  const esc = v => String(v == null ? "" : v).replace(/\r\n|\r|\n/g, " ").replace(/"/g, '""');
  return [h.join(","), ...rows.map(r => h.map(k => `"${esc(r[k] || "")}"`).join(","))].join("\n");
}
