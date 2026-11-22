#!/usr/bin/env node
/** Writes this site's boards into its HTML, so a reader or crawler that runs
 * no JavaScript (GPTBot, ClaudeBot, a link preview) gets each board's pins, and
 * writes what a crawler looks for beside them:
 *
 *   index.html          the listed boards in section#pin-table, a canonical
 *   <board-id>/index.html   one page per listed board: its pin table, its
 *                       own title, description and canonical, data-board
 *   robots.txt, sitemap.xml, llms.txt
 *
 *     node tools/render.mjs
 *
 * Fed from this repo's data/ (boards.json, <id>.json); the HTML is
 * js/pinout.js boardPageHtml / boardListHtml, the functions js/app.js draws
 * the same section with. A board hidden by default (pre-production,
 * unreleased, another maker's reference: ?hidden=1 only) gets no page. Run it
 * after changing index.html or data/ and commit what it writes (README
 * "Render"); a second run changes nothing.
 */
import { readFile, writeFile, mkdir, readdir, rm } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ORIGIN = "https://gpio.hardware.libre.computer";

const { boardPageHtml, boardListHtml, boardTitle, boardDescription, esc } =
  await import(pathToFileURL(path.join(ROOT, "js/pinout.js")).href);

const read = (f) => readFile(path.join(ROOT, f), "utf8");
const meta = (html, re) => (html.match(re) || [, ""])[1];

/** `html` with `content` in section#pin-table (carrying data-board when it is
 *  one board's) and a canonical for `url`. The section ends with a marker, so
 *  a second run replaces its content rather than nesting it. */
function fill(html, content, url, boardId) {
  const section = /<section id="pin-table"[^>]*>[\s\S]*?<\/section><!-- \/pin-table -->/;
  if (!section.test(html)) throw new Error("index.html has no <section id=\"pin-table\">…</section><!-- /pin-table -->");
  const open = `<section id="pin-table"${boardId ? ` data-board="${esc(boardId)}"` : ""} aria-labelledby="pin-table-title">`;
  const out = html.replace(section, () => `${open}${content}</section><!-- /pin-table -->`);
  const canon = `<link rel="canonical" href="${esc(url)}">`;
  return /<link rel="canonical"[^>]*>/.test(out)
    ? out.replace(/<link rel="canonical"[^>]*>/, canon)
    : out.replace(/(<meta name="description"[^>]*>)/, `$1\n${canon}`);
}

const { boards: index } = JSON.parse(await read("data/boards.json"));
const listed = index.filter((b) => !b.hidden);
const urlOf = (id) => `${ORIGIN}/${id ? `${id}/` : ""}`;

// The home page: the listed boards, linked to their pages
let home = await read("index.html");
home = fill(home, boardListHtml(listed), urlOf(null));
await writeFile(path.join(ROOT, "index.html"), home);

// One page per listed board, from the home page's HTML one directory down
for (const entry of listed) {
  const board = JSON.parse(await read(`data/${entry.id}.json`));
  const html = fill(home, boardPageHtml(board), urlOf(entry.id), entry.id)
    .replace(/<title>[^<]*<\/title>/, () => `<title>${esc(boardTitle(board))}</title>`)
    .replace(/(<meta name="description" content=")[^"]*"/, (_, a) => `${a}${esc(boardDescription(board))}"`)
    .replace(/<body([^>]*)>/, (_, a) => `<body${a} data-board="${esc(entry.id)}">`)
    // the site's own files, from one level down
    .replace(/(<link rel="stylesheet" href=")(css\/)/g, "$1../$2")
    .replace(/(<script type="module" src=")(js\/)/g, "$1../$2");
  await mkdir(path.join(ROOT, entry.id), { recursive: true });
  await writeFile(path.join(ROOT, entry.id, "index.html"), html);
}

// A board that left the list (hidden now, or gone): its page goes too -- only
// a directory holding a page this wrote (data-board on its body)
for (const d of await readdir(ROOT, { withFileTypes: true })) {
  if (!d.isDirectory() || listed.some((b) => b.id === d.name)) continue;
  const f = path.join(ROOT, d.name, "index.html");
  if (/<body[^>]* data-board=/.test(await readFile(f, "utf8").catch(() => ""))) {
    await rm(path.join(ROOT, d.name), { recursive: true });
  }
}

await writeFile(path.join(ROOT, "robots.txt"), `User-agent: *\nAllow: /\n\nSitemap: ${ORIGIN}/sitemap.xml\n`);
await writeFile(path.join(ROOT, "sitemap.xml"),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${
    [null, ...listed.map((b) => b.id)].map((id) => `  <url><loc>${esc(urlOf(id))}</loc></url>`).join("\n")}\n</urlset>\n`);

await writeFile(path.join(ROOT, "llms.txt"), [
  `# ${meta(home, /<title>([^<]*)<\/title>/)}`, "",
  `> ${meta(home, /<meta name="description" content="([^"]*)"/)}`, "",
  "Part of Libre Computer (https://libre.computer/llms.txt). Every board page carries its pin table as HTML.", "",
  "## Boards", "",
  ...listed.map((b) => `- [${b.name}](${urlOf(b.id)})`), "",
].join("\n"));

console.log(`rendered index.html, ${listed.length} board pages, robots.txt, sitemap.xml, llms.txt` +
  ` (${index.length - listed.length} hidden boards skipped)`);
