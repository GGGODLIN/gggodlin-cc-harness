#!/usr/bin/env node
// skill-collision-check.js — description 相似度碰撞偵測（skill 路由「擇一」衝突的結構性根源掃描）
//
// Fork 出處：addyosmani/agent-skills scripts/run-evals.js（v0.6.3, 2026-07-11 重評拍板引入）。
// 只留 collision/overlap 檢查，砍掉 Tier 1 結構驗證 / Tier 2 trigger case / Tier 3 behavioral runner。
// 本地新增：CJK bigram 斷詞（上游 tokenizer 的 [^a-z0-9\s-] regex 會整段丟棄中文；
// 本地 skill description 是繁中+英文觸發詞混寫，只靠英文腿分數系統性偏低）。
//
// 用法：
//   node skill-collision-check.js                 # 人讀 markdown 輸出
//   node skill-collision-check.js --pairs-only    # 機器讀 "a|b|score" 行（wrapper diff baseline 用）
//   node skill-collision-check.js <dir> [dir...]  # 自訂掃描目錄（預設 ~/.claude/skills + ~/.claude/commands）
//
// 閾值沿用上游：cosine >= 0.75 collision（✗）、>= 0.5 overlap（⚠）。
// 純確定性計算，零 LLM、零網路。已知限制：lexical approximation——CC 真實路由是模型語意判斷，
// 本工具只抓「description 互撞 / 過寬」兩種主導性 bug，分數低不代表不會互搶。

const fs = require('fs');
const path = require('path');
const os = require('os');

const COLLISION_WARN = 0.5;
const COLLISION_ERROR = 0.75;

const STOP = new Set([
  'a', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'before', 'by', 'for',
  'from', 'in', 'into', 'is', 'it', 'its', 'my', 'need', 'needs', 'of', 'on',
  'or', 'our', 'so', 'that', 'the', 'them', 'this', 'to', 'use', 'when',
  'we', 'with', 'you', 'your', 'help', 'me', 'i', 'do', 'not', 'don',
]);

function stem(t) {
  for (const suf of ['ally', 'ing', 'ed', 'es', 'al']) {
    if (t.length > suf.length + 3 && t.endsWith(suf)) {
      t = t.slice(0, -suf.length);
      break;
    }
  }
  if (t.length > 3 && t.endsWith('s') && !t.endsWith('ss')) t = t.slice(0, -1);
  if (t.length > 4 && t.endsWith('e')) t = t.slice(0, -1);
  if (t.length > 4 && t[t.length - 1] === t[t.length - 2] && !'aeiou'.includes(t[t.length - 1])) {
    t = t.slice(0, -1);
  }
  if (t.length > 3 && t.endsWith('y')) t = t.slice(0, -1) + 'i';
  return t;
}

// 本地新增腿：CJK 連續段落切 bigram（「碰撞偵測」→ 碰撞/撞偵/偵測），單一 CJK 字丟棄避噪
const CJK_RUN = /[一-鿿㐀-䶿]+/g;
function cjkBigrams(text) {
  const grams = [];
  for (const run of text.match(CJK_RUN) || []) {
    if (run.length < 2) continue;
    for (let i = 0; i < run.length - 1; i++) grams.push(run.slice(i, i + 2));
  }
  return grams;
}

function tokenize(text) {
  const ascii = text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, ' ')
    .split(/[\s-]+/)
    .filter((t) => t.length > 2 && !STOP.has(t))
    .map(stem);
  return [...ascii, ...cjkBigrams(text)];
}

function termFreq(tokens) {
  const tf = new Map();
  for (const t of tokens) tf.set(t, (tf.get(t) || 0) + 1);
  return tf;
}

function buildCorpus(skills) {
  const docs = new Map();
  for (const s of skills) {
    const nameTokens = tokenize(s.name.replace(/-/g, ' '));
    docs.set(s.name, termFreq([...nameTokens, ...nameTokens, ...tokenize(s.description)]));
  }
  const df = new Map();
  for (const tf of docs.values()) {
    for (const term of tf.keys()) df.set(term, (df.get(term) || 0) + 1);
  }
  const n = docs.size;
  const idf = (term) => Math.log(1 + n / (1 + (df.get(term) || 0)));
  return { docs, idf };
}

function vec(tf, idf) {
  const v = new Map();
  for (const [term, f] of tf) v.set(term, f * idf(term));
  return v;
}

function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (const [t, w] of a) {
    na += w * w;
    const bw = b.get(t);
    if (bw) dot += w * bw;
  }
  for (const w of b.values()) nb += w * w;
  if (!na || !nb) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

// ---------- loading：frontmatter description（多行 folded 支援）----------

function parseFrontmatter(file) {
  const text = fs.readFileSync(file, 'utf8');
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return null;
  const fm = m[1];
  const nameM = fm.match(/^name:\s*(.+)$/m);
  const descM = fm.match(/^description:\s*([\s\S]*?)(?=\n\w[\w-]*:|$)/m);
  if (!descM) return null;
  const description = descM[1].replace(/\s+/g, ' ').replace(/^['">|-]+\s*/, '').trim();
  return { name: nameM ? nameM[1].trim() : null, description };
}

function collectSkills(dirs) {
  const skills = [];
  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue;
    for (const entry of fs.readdirSync(dir)) {
      const full = path.join(dir, entry);
      let file = null, fallbackName = null;
      if (fs.statSync(full).isDirectory()) {
        const sm = path.join(full, 'SKILL.md');
        if (fs.existsSync(sm)) { file = sm; fallbackName = entry; }
      } else if (entry.endsWith('.md') && entry !== 'INVENTORY.md') {
        file = full;
        fallbackName = entry.replace(/\.md$/, '');
      }
      if (!file) continue;
      const fm = parseFrontmatter(file);
      if (!fm || !fm.description) continue;
      skills.push({ name: fm.name || fallbackName, description: fm.description, file });
    }
  }
  return skills;
}

// ---------- main ----------

const argv = process.argv.slice(2);
const pairsOnly = argv.includes('--pairs-only');
const dirArgs = argv.filter((a) => !a.startsWith('--'));
const HOME = os.homedir();
const dirs = dirArgs.length
  ? dirArgs
  : [path.join(HOME, '.claude', 'skills'), path.join(HOME, '.claude', 'commands')];

const skills = collectSkills(dirs);
const corpus = buildCorpus(skills);
const names = [...corpus.docs.keys()].sort();

const hits = [];
for (let i = 0; i < names.length; i++) {
  for (let j = i + 1; j < names.length; j++) {
    const sim = cosine(vec(corpus.docs.get(names[i]), corpus.idf), vec(corpus.docs.get(names[j]), corpus.idf));
    if (sim >= COLLISION_WARN) {
      hits.push({ a: names[i], b: names[j], sim });
    }
  }
}
hits.sort((x, y) => y.sim - x.sim);

if (pairsOnly) {
  for (const h of hits) console.log(`${h.a}|${h.b}|${h.sim.toFixed(6)}`);
  process.exit(0);
}

console.log(`# Skill description 碰撞掃描`);
console.log(`\n掃描 ${skills.length} 個 description（${dirs.join(', ')}）\n`);
if (!hits.length) {
  console.log('無 >= 50% 相似 pair。');
} else {
  console.log('| 級別 | pair | 相似度 |');
  console.log('|---|---|---|');
  for (const h of hits) {
    const lvl = h.sim >= COLLISION_ERROR ? '✗ collision' : '⚠ overlap';
    console.log(`| ${lvl} | ${h.a} ↔ ${h.b} | ${(h.sim * 100).toFixed(0)}% |`);
  }
  console.log(`\n共 ${hits.length} pair（✗ >= 75% / ⚠ >= 50%）。CJK bigram 腿已開；分數是 lexical 近似、低分不保證不互搶。`);
}
