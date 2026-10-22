import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { checkBuiltRepositoryLinks } from './check-repository-links.mjs';
import { strictChunkMarker } from './strict-pagefind.mjs';

const root = resolve("dist");
async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  return (
    await Promise.all(
      entries.map((e) =>
        e.isDirectory() ? walk(join(dir, e.name)) : join(dir, e.name),
      ),
    )
  ).flat();
}
const files = (await walk(root)).filter((file) => file.endsWith(".html"));
const documents = new Map(
  await Promise.all(
    files.map(async (file) => [file, await readFile(file, "utf8")]),
  ),
);
const problems = [];
// Every query chunk must reject failed loads in both worker and main-thread paths.
for (const file of ['pagefind.js', 'pagefind-worker.js']) {
  if (!(await readFile(join(root, 'pagefind', file), 'utf8')).includes(strictChunkMarker))
    problems.push(`Missing strict Pagefind chunk failure handling in ${file}.`);
}
const queryChunks = await readdir(join(root, "pagefind", "index"));
for (const language of ["zh-cn", "en"]) {
  const chunks = queryChunks.filter(
    (file) => file.startsWith(`${language}_`) && file.endsWith(".pf_index"),
  );
  if (!chunks.length)
    problems.push(
      `Missing ${language} query index chunks.`,
    );
}
for (const locale of ["zh", "en"])
  for (const slug of [
    "overview",
    "installation",
    "quickstart",
    "app-tutorial",
    "concepts",
    "models-tools",
    "sessions-memory",
    "user-input",
    "workflows",
    "integrations",
    "operations",
    "recovery",
    "api-reference",
    "testing",
  ]) {
    if (!documents.has(join(root, locale, "docs", slug, "index.html")))
      problems.push(`Missing guide: /${locale}/docs/${slug}/`);
  }
let links = 0;
for (const [file, html] of documents) {
  if (!/<html[^>]*lang="(?:zh-CN|en)"/.test(html))
    problems.push(`${file}: missing language`);
  if ((html.match(/<h1(?:\s|>)/g) ?? []).length !== 1)
    problems.push(`${file}: expected exactly one h1`);
  for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const ref = match[1].replaceAll("&amp;", "&");
    if (/^(https?:|mailto:|data:|javascript:)/.test(ref)) continue;
    if (ref.startsWith("//")) continue;
    const base = `https://local.test/${file.slice(root.length + 1).replace(/index\.html$/, "")}`;
    const url = new URL(ref, base);
    let target = resolve(root, `.${decodeURIComponent(url.pathname)}`);
    if (!target.startsWith(root + "/") && target !== root) {
      problems.push(`${ref}: outside build directory`);
      continue;
    }
    try {
      if ((await stat(target)).isDirectory())
        target = join(target, "index.html");
      await stat(target);
    } catch {
      problems.push(`${file.slice(root.length)}: broken local URL ${ref}`);
      continue;
    }
    links++;
    if (url.hash && documents.has(target)) {
      const id = decodeURIComponent(url.hash.slice(1));
      const ids = [...documents.get(target).matchAll(/id="([^"]+)"/g)].map(
        (m) => m[1],
      );
      if (!ids.includes(id))
        problems.push(`${file.slice(root.length)}: missing anchor ${ref}`);
    }
  }
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
await checkBuiltRepositoryLinks(root);
console.log(
  `Build integrity: ${files.length} pages, ${links} local links/assets checked.`,
);
