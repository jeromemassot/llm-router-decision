/**
 * markdown.js
 * Zero-dependency, XSS-safe GitHub-Flavored Markdown renderer supporting:
 *  - Fenced code blocks (```lang ... ```)
 *  - Tables (| A | B | with :--- / :---: / ---: alignment)
 *  - Headings (# .. ######), horizontal rules (---), blockquotes (>)
 *  - Ordered & unordered lists (with indentation nesting)
 *  - Inline code (`...`), bold (**...**), italic (*...*), strikethrough (~~...~~), and safe https links
 */

export function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatInline(rawText) {
  if (!rawText) return "";

  // 1. Extract inline code spans first so underscores/asterisks inside `code_vars` are never mangled
  const codeTokens = [];
  let text = String(rawText).replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = codeTokens.length;
    codeTokens.push(`<code>${escapeHtml(code)}</code>`);
    return `\u0000CODE_${idx}\u0000`;
  });

  // 2. Escape remaining HTML
  text = escapeHtml(text);

  // 3. Safe Markdown links [label](https://...)
  text = text.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // 4. Bold + Italic, Bold, Italic, Strikethrough
  text = text
    .replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>");

  // 5. Restore protected inline code spans
  text = text.replace(/\u0000CODE_(\d+)\u0000/g, (_, idx) => codeTokens[Number(idx)] || "");

  return text;
}

function isTableSeparator(line) {
  if (!line || !line.includes("|")) return false;
  const trimmed = line.trim().replace(/^\||\|$/g, "");
  const cells = trimmed.split("|").map((c) => c.trim());
  return cells.length >= 2 && cells.every((c) => /^:?-{3,}:?$/.test(c));
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());
}

function parseTableAlignments(sepLine) {
  return splitTableRow(sepLine).map((cell) => {
    if (cell.startsWith(":") && cell.endsWith(":")) return "center";
    if (cell.endsWith(":")) return "right";
    return "left";
  });
}

export function renderMarkdown(markdown) {
  const src = String(markdown ?? "").replace(/\r\n/g, "\n");
  if (!src.trim()) return "";

  const lines = src.split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // Blank line
    if (!trimmed) {
      i++;
      continue;
    }

    // 1. Fenced Code Block (``` or ~~~)
    const fenceMatch = trimmed.match(/^(```+|~~~+)\s*([A-Za-z0-9_+.-]*)\s*$/);
    if (fenceMatch) {
      const fence = fenceMatch[1];
      const lang = fenceMatch[2] || "";
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // skip closing fence
      const langHeader = lang
        ? `<div class="md-code-header"><span class="md-code-lang">${escapeHtml(lang)}</span></div>`
        : "";
      out.push(
        `<div class="md-code-block">${langHeader}<pre class="md-pre"><code>${escapeHtml(
          codeLines.join("\n")
        )}</code></pre></div>`
      );
      continue;
    }

    // 2. Horizontal Rule
    if (/^(-\s*){3,}$|^(\*\s*){3,}$|^(_\s*){3,}$/.test(trimmed)) {
      out.push("<hr />");
      i++;
      continue;
    }

    // 3. ATX Headings (# .. ######)
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      out.push(`<h${level}>${formatInline(headingMatch[2])}</h${level}>`);
      i++;
      continue;
    }

    // 4. GFM Table
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const headers = splitTableRow(line);
      const aligns = parseTableAlignments(lines[i + 1]);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        bodyRows.push(splitTableRow(lines[i]));
        i++;
      }
      const thHtml = headers
        .map(
          (h, idx) =>
            `<th style="text-align:${aligns[idx] || "left"}">${formatInline(h)}</th>`
        )
        .join("");
      const tbHtml = bodyRows
        .map(
          (row) =>
            `<tr>${headers
              .map(
                (_, idx) =>
                  `<td style="text-align:${aligns[idx] || "left"}">${formatInline(
                    row[idx] ?? ""
                  )}</td>`
              )
              .join("")}</tr>`
        )
        .join("");
      out.push(
        `<div class="md-table-wrap"><table class="md-table"><thead><tr>${thHtml}</tr></thead><tbody>${tbHtml}</tbody></table></div>`
      );
      continue;
    }

    // 5. Blockquote (> ...)
    if (trimmed.startsWith(">")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      out.push(`<blockquote>${renderMarkdown(quoteLines.join("\n"))}</blockquote>`);
      continue;
    }

    // 6. Lists (Unordered & Ordered, supporting nested sublists)
    const listMatch = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    if (listMatch) {
      const parseList = (baseIndent) => {
        const firstM = lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        const isOrdered = /^\d+\.$/.test(firstM[2]);
        const tag = isOrdered ? "ol" : "ul";
        const items = [];

        while (i < lines.length) {
          const cur = lines[i];
          if (!cur.trim()) {
            // Check if next non-empty line continues this list
            if (
              i + 1 < lines.length &&
              /^\s*([-*+]|\d+\.)\s+/.test(lines[i + 1])
            ) {
              i++;
              continue;
            }
            break;
          }
          const m = cur.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
          if (!m) break;
          const indent = m[1].length;
          if (indent < baseIndent) break;
          if (indent > baseIndent) {
            const nestedHtml = parseList(indent);
            if (items.length > 0) {
              items[items.length - 1] += nestedHtml;
            } else {
              items.push(nestedHtml);
            }
            continue;
          }
          items.push(formatInline(m[3]));
          i++;
        }
        return `<${tag}>${items.map((it) => `<li>${it}</li>`).join("")}</${tag}>`;
      };

      out.push(parseList(listMatch[1].length));
      continue;
    }

    // 7. Paragraph (accumulate consecutive plain lines)
    const paraLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(```+|~~~+|#{1,6}\s|>\s?|(-\s*){3,}$|(\*\s*){3,}$|(_\s*){3,}$)/.test(
        lines[i].trim()
      ) &&
      !/^(\s*)([-*+]|\d+\.)\s+/.test(lines[i]) &&
      !(
        lines[i].includes("|") &&
        i + 1 < lines.length &&
        isTableSeparator(lines[i + 1])
      )
    ) {
      paraLines.push(formatInline(lines[i].trim()));
      i++;
    }
    if (paraLines.length > 0) {
      out.push(`<p>${paraLines.join("<br />")}</p>`);
    } else {
      // Safety fallback so loop always advances
      out.push(`<p>${formatInline(trimmed)}</p>`);
      i++;
    }
  }

  return out.join("\n");
}
