#!/usr/bin/env node
/** Checks tools/render.mjs and the pin table it writes (js/pinout.js), on a
 * scratch copy of the site so the checkout is never touched:
 *
 *   - every listed board gets <id>/index.html with its pins, title,
 *     description, canonical and data-board; no hidden board gets a page
 *   - every pin of every header of the board is a row in its table
 *   - robots.txt is exactly the one libre.computer serves; the sitemap and
 *     llms.txt name the home page and every board page, and nothing hidden
 *   - a second run changes nothing; a board that leaves the list loses its page
 *   - the pin table escapes what it is given
 *
 *     node tools/test-render.mjs        exit 0 clean, 1 on a failure
 */
import { cp, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { tmpdir } from "node:os";
import path from "node:path";
import assert from "node:assert/strict";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ORIGIN = "https://gpio.hardware.libre.computer";
const tmp = await mkdtemp(path.join(tmpdir(), "gpio-render-test-"));
let failed = 0;

async function check(name, fn) {
  try {
    await fn();
    console.log(`ok    ${name}`);
  } catch (e) {
    failed += 1;
    console.log(`FAIL  ${name}\n      ${e.message.split("\n").join("\n      ")}`);
  }
}

async function snapshot(dir) {
  const out = {};
  for (const e of await readdir(dir, { withFileTypes: true, recursive: true })) {
    if (!e.isFile()) continue;
    const f = path.join(e.parentPath ?? e.path, e.name);
    out[path.relative(dir, f)] = await readFile(f, "utf8");
  }
  return out;
}

try {
  for (const f of ["index.html", "js", "data", "tools/render.mjs"]) {
    await cp(path.join(ROOT, f), path.join(tmp, f), { recursive: true });
  }
  const render = () => execFileSync(process.execPath, [path.join(tmp, "tools/render.mjs")], { encoding: "utf8" });
  render();
  const site = (f) => readFile(path.join(tmp, f), "utf8");
  const { boards } = JSON.parse(await site("data/boards.json"));
  const listed = boards.filter((b) => !b.hidden);
  const hidden = boards.filter((b) => b.hidden);

  await check("a page per listed board, with its title, description, canonical and data-board", async () => {
    assert.ok(listed.length > 0);
    for (const b of listed) {
      const html = await site(`${b.id}/index.html`);
      const board = JSON.parse(await site(`data/${b.id}.json`));
      assert.match(html, new RegExp(`<link rel="canonical" href="${ORIGIN}/${b.id}/">`), b.id);
      assert.match(html, new RegExp(`<body[^>]* data-board="${b.id}"`), b.id);
      assert.ok(html.includes(`<title>${board.name} (${board.model}) GPIO Pinout`), `${b.id}: title`);
      assert.match(html, new RegExp(`<meta name="description" content="[^"]*${board.model}`), b.id);
      assert.ok(html.includes('href="../css/style.css"') && html.includes('src="../js/app.js"'), `${b.id}: assets`);
      assert.equal((html.match(/<link rel="canonical"/g) || []).length, 1, `${b.id}: one canonical`);
    }
  });

  await check("no page for a hidden board", async () => {
    assert.ok(hidden.length > 0, "the data has hidden boards to test against");
    for (const b of hidden) {
      await assert.rejects(site(`${b.id}/index.html`), `${b.id} has a page`);
    }
  });

  await check("every pin of every header is a row, inside <main>", async () => {
    for (const b of listed) {
      const html = await site(`${b.id}/index.html`);
      const board = JSON.parse(await site(`data/${b.id}.json`));
      const main = html.slice(html.indexOf("<main"), html.indexOf("</main>"));
      const rows = (main.match(/<tr><th scope="row">/g) || []).length;
      const pins = board.headers.reduce((n, h) => n + h.pins.length, 0);
      assert.equal(rows, pins, `${b.id}: ${rows} rows for ${pins} pins`);
      for (const h of board.headers) assert.ok(main.includes(`<caption>${h.id} · `), `${b.id}: ${h.id}`);
      assert.ok(!/undefined|null/.test(main.slice(main.indexOf('<section id="pin-table"'))), `${b.id}: undefined/null in the table`);
    }
  });

  await check("index.html lists the boards and carries the home canonical", async () => {
    const html = await site("index.html");
    assert.match(html, new RegExp(`<link rel="canonical" href="${ORIGIN}/">`));
    assert.doesNotMatch(html, /<body[^>]* data-board=/);
    for (const b of listed) assert.ok(html.includes(`<a href="/${b.id}/">`), b.id);
    for (const b of hidden) assert.ok(!html.includes(`"/${b.id}/"`), `${b.id} listed`);
  });

  await check("robots.txt, sitemap.xml, llms.txt", async () => {
    assert.equal(await site("robots.txt"), `User-agent: *\nContent-Signal: search=yes, ai-input=yes, ai-train=yes\nAllow: /\n\nSitemap: ${ORIGIN}/sitemap.xml\n`);
    const locs = [...(await site("sitemap.xml")).matchAll(/<loc>([^<]*)<\/loc>/g)].map((m) => m[1]);
    assert.deepEqual(locs, [`${ORIGIN}/`, ...listed.map((b) => `${ORIGIN}/${b.id}/`)]);
    const llms = await site("llms.txt");
    assert.match(llms, /^# Libre Computer GPIO Pinout\n\n> .+\n\n.*https:\/\/libre\.computer\/llms\.txt.*\n\n## Boards\n\n/);
    for (const b of listed) assert.ok(llms.includes(`- [${b.name}](${ORIGIN}/${b.id}/)`), b.id);
    for (const b of hidden) assert.ok(!llms.includes(`/${b.id}/`), `${b.id} in llms.txt`);
  });

  await check("a second run changes nothing", async () => {
    const before = await snapshot(tmp);
    render();
    assert.deepEqual(await snapshot(tmp), before);
  });

  await check("a board that leaves the list loses its page", async () => {
    const f = path.join(tmp, "data/boards.json");
    const data = JSON.parse(await readFile(f, "utf8"));
    const gone = data.boards.find((b) => !b.hidden);
    gone.hidden = true;
    await writeFile(f, JSON.stringify(data));
    render();
    await assert.rejects(site(`${gone.id}/index.html`));
    assert.ok(!(await site("sitemap.xml")).includes(`/${gone.id}/`));
  });

  await check("the pin table escapes its input", async () => {
    const { boardPageHtml, boardListHtml } = await import(pathToFileURL(path.join(ROOT, "js/pinout.js")).href);
    const evil = "<img src=x onerror=alert(1)>";
    const board = { id: "x", name: evil, model: evil, vendor: "V", soc: "S", status: "production",
      headers: [{ id: evil, rows: 1, pins: [{ pin: 1, name: evil, ref: evil, type: "gpio", cls: "gpio",
        funcs: [evil], chip: 0, line: 1, sysfs: null, pad: "A1" }] }] };
    for (const html of [boardPageHtml(board), boardListHtml([{ ...board, npins: 1 }])]) {
      assert.ok(!html.includes("<img"), html);
    }
  });
} finally {
  await rm(tmp, { recursive: true, force: true });
}

console.log(failed ? `FAIL  ${failed} check(s)` : "OK  render");
process.exit(failed ? 1 : 0);
