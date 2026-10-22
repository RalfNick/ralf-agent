import { readFile, writeFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { repositoryInfo } from '../src/lib/repository.mjs';

const locales = ["zh", "en"];
const sha = (text) => createHash("sha256").update(text).digest("hex");
const current = {};
const problems = [];
const zhFiles = (await readdir("src/content/guides/zh"))
  .filter((file) => file.endsWith(".md"))
  .sort();
const enFiles = (await readdir("src/content/guides/en"))
  .filter((file) => file.endsWith(".md"))
  .sort();
if (JSON.stringify(zhFiles) !== JSON.stringify(enFiles))
  problems.push("Chinese and English guide sets differ.");
for (const file of zhFiles) {
  const entry = { translations: {}, sources: {} };
  let expectedSources;
  for (const locale of locales) {
    const text = await readFile(`src/content/guides/${locale}/${file}`, "utf8");
    entry.translations[locale] = sha(text);
    for (const match of text.matchAll(/git (?:checkout|show) ([a-f0-9]{40})/g))
      if (match[1] !== repositoryInfo.ref)
        problems.push(`${locale}/${file}: tutorial Git ref differs from repository.json.`);
    const sources = text
      .match(/^sources: \[([^\]]+)\]/m)?.[1]
      .split(",")
      .map((s) => s.trim())
      .sort();
    if (!sources?.length) {
      problems.push(`${locale}/${file}: no sources`);
      continue;
    }
    if (
      expectedSources &&
      JSON.stringify(expectedSources) !== JSON.stringify(sources)
    )
      problems.push(`${file}: locale source sets differ`);
    expectedSources = sources;
    for (const source of sources) {
      if (
        !/^(docs\/[\w./-]+\.md|README\.md)$/.test(source) ||
        source.includes("..")
      )
        throw new Error(`Invalid source path: ${source}`);
      entry.sources[source] = sha(await readFile(`../${source}`, "utf8"));
    }
  }
  current[file.replace(".md", "")] = entry;
}
const path = "docs-source-lock.json";
if (process.argv.includes("--record") && !problems.length) {
  await writeFile(
    path,
    JSON.stringify(
      {
        note: "Record only after reviewing both locales against the listed repository sources.",
        repository: repositoryInfo,
        guides: current,
      },
      null,
      2,
    ) + "\n",
  );
  console.log("Recorded reviewed bilingual guides and source hashes.");
} else {
  const saved = JSON.parse(await readFile(path, "utf8"));
  if (JSON.stringify(saved.repository) !== JSON.stringify(repositoryInfo))
    problems.push('Documentation baseline changed; review both locales and record a new snapshot.');
  for (const [slug, entry] of Object.entries(current))
    if (JSON.stringify(saved.guides[slug]) !== JSON.stringify(entry))
      problems.push(
        `${slug}: source or translation changed. Review both languages, then run node scripts/check-docs.mjs --record.`,
      );
  if (
    JSON.stringify(Object.keys(saved.guides).sort()) !==
    JSON.stringify(Object.keys(current).sort())
  )
    problems.push("Guide manifest is incomplete.");
  if (problems.length) {
    console.error(problems.join("\n"));
    process.exit(1);
  }
  console.log(
    `Documentation: ${zhFiles.length} bilingual guide pairs match reviewed sources.`,
  );
}
