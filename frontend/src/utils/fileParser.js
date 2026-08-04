// ── File parsing utilities ────────────────────────────────────────────────────

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

export async function loadScript(url) {
  return new Promise((res, rej) => {
    if (document.querySelector(`script[src="${url}"]`)) return res();
    const s = document.createElement("script");
    s.src = url; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });
}

export async function extractZipPDFs(zipFile) {
  await loadScript("https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js");
  const zip = await window.JSZip.loadAsync(zipFile);
  const pdfs = [];
  for (const [name, entry] of Object.entries(zip.files)) {
    if (name.toLowerCase().endsWith(".pdf") && !entry.dir) {
      const blob = await entry.async("blob");
      pdfs.push(new File([blob], name, { type: "application/pdf" }));
    }
  }
  return pdfs.sort((a, b) => a.name.localeCompare(b.name));
}

export function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length) return [];
  const headers = lines[0].split(",").map(h => h.trim().replace(/^"|"$/g, ""));
  return lines.slice(1).map(line => {
    const cols = []; let cur = "", inQ = false;
    for (const ch of line) {
      if (ch === '"') { inQ = !inQ; }
      else if (ch === "," && !inQ) { cols.push(cur.trim()); cur = ""; }
      else cur += ch;
    }
    cols.push(cur.trim());
    const row = {};
    headers.forEach((h, i) => { row[h] = (cols[i] || "").replace(/^"|"$/g, ""); });
    return row;
  });
}

export async function parseXLSX(file) {
  await loadScript("https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js");
  const buf = await file.arrayBuffer();
  const wb = window.XLSX.read(buf, { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return window.XLSX.utils.sheet_to_json(ws, { defval: "" });
}

// Sanitise rows: replace newlines in all field values with spaces
export function sanitiseRows(rows) {
  return rows.map(row => {
    const clean = {};
    for (const [k, v] of Object.entries(row)) {
      clean[k] = String(v == null ? "" : v)
        .replace(/\r\n|\r|\n/g, " ")
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
