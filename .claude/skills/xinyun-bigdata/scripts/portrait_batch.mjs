import fs from 'node:fs'
import path from 'node:path'
import {
  BASE,
  STATE,
  OUT,
  DATE_DEFAULT,
  getThirdLabels,
  matchLabels,
  describeLabel,
  fetchIndicators,
  buildSummary,
  launch,
} from './lib.mjs'

// 批量拉取方案线路的新云大数据 2023-05 受众画像与时段人流密度（单次浏览器会话 + 本地缓存）
// 用法:
//   node portrait_batch.mjs --lines "71路,17路,136路" --media 公交 --max-per-line 6 --json

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}

const linesArg = arg('--lines', '')
const media = arg('--media', '公交')
const date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const maxPerLine = Math.max(0, Math.min(12, Number(arg('--max-per-line', 6))))
const force = process.argv.includes('--force')
const jsonMode = process.argv.includes('--json')
const outDir = path.resolve(arg('--out', OUT))
const cacheFile = path.join(outDir, 'portrait_cache.json')

const requestedLines = linesArg.split(',').map((s) => s.trim()).filter(Boolean)
if (!requestedLines.length) {
  const err = { ok: false, error: 'INVALID_ARGS', message: '缺少 --lines 参数' }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error(err.message)
  process.exit(2)
}

function readCache() {
  try {
    return JSON.parse(fs.readFileSync(cacheFile, 'utf8'))
  } catch {
    return { per_line: {}, aggregate: {} }
  }
}

function writeCache(cache) {
  fs.mkdirSync(outDir, { recursive: true })
  const tmp = cacheFile + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(cache, null, 2), 'utf8')
  fs.renameSync(tmp, cacheFile)
}

const cache = readCache()
cache.per_line = cache.per_line || {}
cache.aggregate = cache.aggregate || {}

const aggKey = `${media}:${date}:${[...new Set(requestedLines)].sort().join('|')}`
const topLines = requestedLines.slice(0, maxPerLine)

const allPerLineCached = !force && topLines.every((l) => cache.per_line[`${media}:${date}:${l}`])
const aggCached = !force && Boolean(cache.aggregate[aggKey])

if (aggCached && allPerLineCached) {
  const agg = cache.aggregate[aggKey]
  const perLine = {}
  for (const l of topLines) {
    perLine[l] = cache.per_line[`${media}:${date}:${l}`]
  }
  const payload = {
    ok: true,
    status: 'ready',
    cached: true,
    source: '新云传媒大数据可视化平台 · 组合查询（2023-05）',
    data_month: date,
    media,
    requested: requestedLines,
    matched: agg.matched || [],
    missing: agg.missing || [],
    aggregate: agg.summary || null,
    per_line: perLine,
    fetched_at: agg.fetched_at || new Date().toISOString(),
  }
  if (jsonMode) console.log(JSON.stringify(payload))
  else console.log(`画像命中缓存: matched=${payload.matched.length}, per_line=${Object.keys(perLine).length}`)
  process.exit(0)
}

if (!fs.existsSync(STATE)) {
  const err = {
    ok: false,
    status: 'skipped',
    reason: 'MANUAL_LOGIN_REQUIRED',
    message: '缺少登录会话，请先运行 login.mjs',
  }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error(err.message)
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)

  const all = await getThirdLabels(page, media)
  const { labels, missing } = matchLabels(all, requestedLines)

  if (!labels.length) {
    const out = {
      ok: true,
      status: 'degraded',
      reason: 'NO_MATCHED_LABELS',
      source: '新云传媒大数据可视化平台 · 组合查询（2023-05）',
      data_month: date,
      media,
      requested: requestedLines,
      matched: [],
      missing,
      aggregate: null,
      per_line: {},
      fetched_at: new Date().toISOString(),
    }
    if (jsonMode) console.log(JSON.stringify(out))
    else console.log('未匹配到任何线路标签:', missing.join(', '))
    process.exit(0)
  }

  // 1) Aggregate portrait for all matched lines combined
  const aggIds = labels.map((x) => String(x.id))
  const aggIndicators = await fetchIndicators(page, aggIds, date)
  const aggSummary = buildSummary(aggIndicators)
  const matchedMeta = labels.map((x) => ({
    ...describeLabel(x),
    requested: x._requested || x.thirdLabel,
  }))
  const fetchedAt = new Date().toISOString()

  cache.aggregate[aggKey] = {
    matched: matchedMeta,
    missing,
    summary: aggSummary,
    fetched_at: fetchedAt,
  }

  // 2) Per-line portraits for top matched lines (for click-to-inspect drawer & heatmap weighting)
  const perLine = {}
  const targetLabels = labels.slice(0, maxPerLine)
  for (const lbl of targetLabels) {
    const reqName = lbl._requested || lbl.thirdLabel
    const lk = `${media}:${date}:${reqName}`
    if (!force && cache.per_line[lk]) {
      perLine[reqName] = cache.per_line[lk]
      continue
    }
    const ind = await fetchIndicators(page, [String(lbl.id)], date)
    const sum = buildSummary(ind)
    const entry = {
      label: describeLabel(lbl),
      requested: reqName,
      summary: sum,
      fetched_at: fetchedAt,
    }
    cache.per_line[lk] = entry
    perLine[reqName] = entry
  }

  writeCache(cache)

  const payload = {
    ok: true,
    status: 'ready',
    cached: false,
    source: '新云传媒大数据可视化平台 · 组合查询（2023-05）',
    data_month: date,
    media,
    requested: requestedLines,
    matched: matchedMeta,
    missing,
    aggregate: aggSummary,
    per_line: perLine,
    fetched_at: fetchedAt,
  }
  if (jsonMode) console.log(JSON.stringify(payload))
  else {
    console.log(`画像拉取完成: 匹配 ${matchedMeta.length}/${requestedLines.length} 条, 单线画像 ${Object.keys(perLine).length} 条`)
    console.log(`  PV=${aggSummary.cover_pv} UV=${aggSummary.cover_uv} 男性=${aggSummary.male_pct}% 女性=${aggSummary.female_pct}%`)
  }
} catch (e) {
  const err = { ok: false, status: 'degraded', reason: 'PORTRAIT_ERROR', message: e.message }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error('PORTRAIT_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
