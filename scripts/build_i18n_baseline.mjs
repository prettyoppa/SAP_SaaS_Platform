/**
 * Extracts { en, ko } from app/static/js/i18n.js → app/data/i18n_baseline.json
 * Run: node scripts/build_i18n_baseline.mjs
 */
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const i18nPath = join(root, "app", "static", "js", "i18n.js");
const outPath = join(root, "app", "data", "i18n_baseline.json");

let s = readFileSync(i18nPath, "utf8");
s = s.replace(/\/\*[\s\S]*?\*\//g, "");

const marker = "const TRANSLATIONS = ";
const start = s.indexOf(marker);
if (start < 0) throw new Error("TRANSLATIONS not found");
const open = s.indexOf("{", start);
if (open < 0) throw new Error("{ not found");

function extractBalanced(str, openIdx) {
  let depth = 0;
  let inStr = false;
  let strCh = "";
  let esc = false;
  for (let i = openIdx; i < str.length; i++) {
    const c = str[i];
    if (inStr) {
      if (esc) {
        esc = false;
        continue;
      }
      if (c === "\\") {
        esc = true;
        continue;
      }
      if (c === strCh) {
        inStr = false;
        strCh = "";
      }
      continue;
    }
    if (c === '"' || c === "'") {
      inStr = true;
      strCh = c;
      continue;
    }
    if (c === "{") depth++;
    if (c === "}") {
      depth--;
      if (depth === 0) return str.slice(openIdx, i + 1);
    }
  }
  throw new Error("unbalanced braces");
}

const objLiteral = extractBalanced(s, open);
// eslint-disable-next-line no-new-func
const TRANSLATIONS = new Function(`return ${objLiteral}`)();
if (!TRANSLATIONS?.en || !TRANSLATIONS?.ko) throw new Error("missing en/ko");

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(
  outPath,
  JSON.stringify({ en: TRANSLATIONS.en, ko: TRANSLATIONS.ko }, null, 0),
  "utf8"
);
console.log("Wrote", outPath, "keys en:", Object.keys(TRANSLATIONS.en).length, "ko:", Object.keys(TRANSLATIONS.ko).length);
