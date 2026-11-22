import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, apiRequest, flattenTree } from './lib.mjs'

// AI线路批量只读：一次浏览器会话取多条方案线路的真实几何，供提案地图使用。
// 输出纯 JSON（stdout）；人类可读摘要只写 stderr。只读，不调用 saveWeb / ai_share。
//
// Examples:
//   node ai_route_batch.mjs --lines "136,157,17"
//   node ai_route_batch.mjs --lines "136,157" --force
//   node ai_route_batch.mjs --lines "136,157" --cached-only
//
// 缓存：<out>/ai_line_<lineId>.geojson（与 ai_route.mjs 共用），按 meta.fetchedAt
// 判断 TTL；全部命中且未 --force 时不启动浏览器，无会话也能复用缓存。

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
function flag(name) {
  return process.argv.includes(name)
}

const linesArg = arg('--lines', '')
const outDir = path.resolve(arg('--out', OUT))
const maxAgeDays = Number(arg('--max-age-days', '30'))
const maxLines = Math.max(1, Number(arg('--max', '60')) || 60)
const force = flag('--force')
const cachedOnly = flag('--cached-only')
// AI线路数据是 2023-05 轨迹快照，几何本身静态；30 天 TTL 只控制平台刷新。
const headers = {
  Accept: 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
  Referer: BASE + '/busLineShowSolution',
}

const norm = (s) => String(s ?? '').replace(/路$/g, '').replace(/\s+/g, '').trim()
const nowIso = () => new Date().toISOString()
const requested = [...new Set(String(linesArg).split(',').map((s) => norm(s)).filter(Boolean))]
  .filter((s) => /^[\w一-龥()\-]{1,32}$/.test(s))
  .slice(0, maxLines)

fs.mkdirSync(outDir, { recursive: true })

function finish(payload, code = 0) {
  const out = { platform: BASE, data_month: '202305', fetched_at: nowIso(), ...payload }
  if (!out.summary) {
    out.summary = {
      requested: requested.length,
      resolved: out.lines?.length || 0,
      cached: (out.lines || []).filter((x) => x.status === 'cached').length,
      fetched: (out.lines || []).filter((x) => x.status === 'fetched').length,
      missing: (out.missing || []).length,
    }
  }
  process.stdout.write(JSON.stringify(out) + '\n')
  process.exit(code)
}

// --check：只探测会话是否有效（不启动浏览器、不写文件），供 Agent 决定是否
// 跳过其他 xinyun 页面脚本，避免会话过期时白等 Playwright。
if (flag('--check')) {
  let result = { ok: false, authenticated: false, http_status: null, reason: 'MANUAL_LOGIN_REQUIRED' }
  if (!fs.existsSync(STATE)) {
    finish(result)
  }
  let client = null
  try {
    client = await apiRequest.newContext({ storageState: STATE, ignoreHTTPSErrors: true })
    const resp = await client.get(BASE + '/baseInfoLine/getTreeLine', { headers, maxRedirects: 0 })
    const location = resp.headers()['location'] || ''
    const authenticated = resp.status() === 200
    result = {
      ok: authenticated,
      authenticated,
      http_status: resp.status(),
      reason: authenticated ? null : (/login/i.test(location) ? 'MANUAL_LOGIN_REQUIRED' : 'PROBE_FAILED'),
      location: location || null,
    }
  } catch (e) {
    result = { ok: false, authenticated: false, http_status: null, reason: 'PROBE_FAILED', error: String(e.message || e).slice(0, 160) }
  } finally {
    if (client) await client.dispose()
  }
  finish(result)
}

if (!requested.length) {
  finish({ ok: false, status: 'skipped', reason: 'NO_LINES', lines: [], missing: [], summary: { requested: 0, resolved: 0, cached: 0, fetched: 0, missing: 0 } })
}

// ---------------------------------------------------------------------------
// 缓存索引：扫描同目录 ai_line_*.geojson，按 properties.lineName 归一化。
// ---------------------------------------------------------------------------
function loadCacheIndex() {
  const index = new Map()
  let files = []
  try {
    files = fs.readdirSync(outDir).filter((f) => /^ai_line_.+\.geojson$/i.test(f))
  } catch {
    return index
  }
  for (const file of files) {
    const full = path.join(outDir, file)
    try {
      const raw = JSON.parse(fs.readFileSync(full, 'utf8'))
      const feature = (raw.features || []).find((f) => f?.properties?.lineName)
      const props = feature?.properties || {}
      const coords = feature?.geometry?.coordinates || []
      if (!props.lineName || !Array.isArray(coords) || coords.length < 2) continue
      const fetchedAt = raw.meta?.fetchedAt || fs.statSync(full).mtime.toISOString()
      const ageDays = (Date.now() - Date.parse(fetchedAt)) / 86400000
      const key = norm(props.lineName)
      const prev = index.get(key)
      if (prev && Date.parse(prev.fetchedAt) > Date.parse(fetchedAt)) continue
      index.set(key, {
        requested: key,
        line: key,
        matched: true,
        lineName: props.lineName,
        lineId: props.lineId ?? null,
        status: 'cached',
        points: coords.length,
        path: coords,
        bbox: bbox(coords),
        file: full,
        fetched_at: fetchedAt,
        stale: !Number.isFinite(ageDays) || ageDays > maxAgeDays,
      })
    } catch {
      /* ignore malformed cache file; it will be refetched if possible */
    }
  }
  return index
}

function bbox(coords) {
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity
  for (const [lng, lat] of coords) {
    if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue
    if (lng < minLng) minLng = lng
    if (lat < minLat) minLat = lat
    if (lng > maxLng) maxLng = lng
    if (lat > maxLat) maxLat = lat
  }
  return Number.isFinite(minLng) ? [minLng, minLat, maxLng, maxLat] : null
}

function stripInternal(line) {
  const { stale, ...rest } = line
  return rest
}

const cache = loadCacheIndex()
const cacheHits = new Map()
const missing = []

// 地铁线路在平台树里常带分支后缀（如“地铁11号线(嘉定北)”）；按前缀复用缓存，
// 并把输出键归一到请求的线路名，编排层才能稳定匹配。
function cacheHitFor(line) {
  const exact = cache.get(line)
  if (exact) return exact
  if (/^地铁/.test(line)) {
    for (const [key, value] of cache) {
      if (key.startsWith(line)) return value
    }
  }
  return null
}

for (const line of requested) {
  const hit = cacheHitFor(line)
  if (hit && !hit.stale && !force) cacheHits.set(line, { ...stripInternal(hit), requested: line, line })
  else missing.push(line)
}

// 全部命中：不启动浏览器（无会话也能出图）。
if (!missing.length) {
  finish({
    ok: true,
    status: 'ready',
    reason: null,
    lines: requested.map((line) => cacheHits.get(line)),
    missing: [],
    cache_only: true,
  })
}

if (cachedOnly) {
  finish({
    ok: false,
    status: 'degraded',
    reason: 'CACHED_ONLY',
    lines: requested.map((line) => cacheHits.get(line)).filter(Boolean),
    missing: missing.map((line) => ({ requested: line, reason: 'CACHED_ONLY' })),
  })
}

if (!fs.existsSync(STATE)) {
  finish({
    ok: false,
    status: 'skipped',
    reason: 'MANUAL_LOGIN_REQUIRED',
    lines: requested.map((line) => cacheHits.get(line)).filter(Boolean),
    missing: missing.map((line) => ({ requested: line, reason: 'MANUAL_LOGIN_REQUIRED' })),
  })
}

// ---------------------------------------------------------------------------
// 平台会话：一次登录态 → 一次线路树 → 逐条取几何。
// 用 context.request（共享 storageState 的 cookie），不加载页面，避开 nginx
// https→http 重定向；会话过期时平台返回 302→/login，显式标记人工登录。
// ---------------------------------------------------------------------------
const fetched = new Map()
let reason = null

try {
  // APIRequestContext 共享 storageState cookie，不会加载页面/触发 nginx 重定向。
  const client = await apiRequest.newContext({ storageState: STATE, ignoreHTTPSErrors: true })
  try {
    const request = client
    const treeResp = await request.get(BASE + '/baseInfoLine/getTreeLine', { headers, maxRedirects: 0 })
    if (treeResp.status() !== 200) {
      const location = treeResp.headers()['location'] || ''
      reason = /login/i.test(location) ? 'MANUAL_LOGIN_REQUIRED' : 'TREE_UNAVAILABLE'
      throw new Error(reason)
    }
    let tree = null
    try { tree = await treeResp.json() } catch { /* HTML login page / error */ }
    if (!tree) {
      reason = 'TREE_UNAVAILABLE'
      throw new Error(reason)
    }
    const flat = flattenTree(tree.data ?? tree)

    for (const line of missing) {
      let hits = flat.filter((n) => n.lineName && norm(n.lineName) === line)
      // 地铁线路常有分支后缀：请求“地铁11号线”时匹配“地铁11号线(嘉定北/花桥)”。
      if (!hits.length && /^地铁/.test(line)) {
        hits = flat.filter((n) => n.lineName && norm(n.lineName).startsWith(line))
      }
      if (!hits.length) {
        const suggestions = flat
          .filter((n) => n.lineName && String(n.lineName).includes(line))
          .slice(0, 8)
          .map((n) => `${n.lineName} (lineId=${n.lineId})`)
        fetched.set(line, { error: 'NOT_FOUND', suggestions })
        continue
      }
      if (hits.length > 1) {
        // 同名多节点（如不同分公司/版本）：稳定取 lineId 最小的一条。
        hits.sort((a, b) => String(a.lineId).localeCompare(String(b.lineId), 'en', { numeric: true }))
      }
      const node = hits[0]
      const linePath = node.linePath || node.path || node.lineName
      try {
        const geoResp = await request.get(
          BASE + '/baseInfoLine/getLineJson?linePath=' + encodeURIComponent(linePath),
          { headers, maxRedirects: 0 },
        )
        if (geoResp.status() !== 200) throw new Error('GEOMETRY_HTTP_' + geoResp.status())
        let geo = null
        try { geo = await geoResp.json() } catch { throw new Error('GEOMETRY_NOT_JSON') }
        let inner = geo?.data
        if (typeof inner === 'string') {
          try { inner = JSON.parse(inner) } catch { inner = null }
        }
        const points = Array.isArray(inner?.path) ? inner.path : []
        // 平台返回 {lng:<latitude>, lat:<longitude>}；交换为 GeoJSON [lon,lat]。
        const coords = points
          .map((p) => [Number(p.lat), Number(p.lng)])
          .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat))
        if (coords.length < 2) {
          fetched.set(line, { error: 'EMPTY_GEOMETRY' })
          continue
        }
        const feature = {
          type: 'Feature',
          properties: {
            lineId: node.lineId,
            lineName: node.lineName,
            source: '新云大数据可视化平台 /baseInfoLine/getLineJson',
          },
          geometry: { type: 'LineString', coordinates: coords },
        }
        const geojson = {
          type: 'FeatureCollection',
          features: [feature],
          meta: {
            platform: BASE,
            fetchedAt: nowIso(),
            dataMonth: '202305',
            note: '坐标已由平台 lng/lat 字段交换纠正为 [lng,lat]；仅用于可视化。',
          },
        }
        const safeId = String(node.lineId || line).replace(/[^\w-]+/g, '_')
        const file = path.join(outDir, `ai_line_${safeId}.geojson`)
        const tmp = file + '.tmp'
        fs.writeFileSync(tmp, JSON.stringify(geojson, null, 2), 'utf8')
        fs.renameSync(tmp, file)
        fetched.set(line, {
          requested: line,
          line: line,
          matched: true,
          lineName: node.lineName,
          lineId: node.lineId ?? null,
          status: 'fetched',
          points: coords.length,
          path: coords,
          bbox: bbox(coords),
          file,
          fetched_at: geojson.meta.fetchedAt,
        })
      } catch (e) {
        fetched.set(line, { error: `GEOMETRY_ERROR:${String(e.message || e).slice(0, 120)}` })
      }
    }
  } finally {
    await client.dispose()
  }
} catch (e) {
  if (!reason) reason = /登录|login|密码|验证码/i.test(String(e.message)) ? 'MANUAL_LOGIN_REQUIRED' : 'BATCH_UNAVAILABLE'
}

const resolved = []
const unresolved = []
for (const line of requested) {
  const hit = cacheHits.get(line) || fetched.get(line)
  if (hit && !hit.error) resolved.push(hit)
  else unresolved.push({
    requested: line,
    reason: hit?.error || reason || 'NOT_FOUND',
    suggestions: hit?.suggestions || [],
  })
}

// 去重：missing 在循环中可能被重复收集，这里统一按 requested 输出。
const unresolvedUnique = []
const seen = new Set()
for (const item of unresolved) {
  if (seen.has(item.requested)) continue
  seen.add(item.requested)
  unresolvedUnique.push(item)
}

let status = 'ready'
if (!resolved.length) status = reason === 'MANUAL_LOGIN_REQUIRED' ? 'skipped' : 'degraded'
else if (unresolvedUnique.length) status = 'degraded'

finish({
  ok: status === 'ready',
  status,
  reason: status === 'ready' ? null : (reason || 'PARTIAL_ROUTES'),
  lines: resolved,
  missing: unresolvedUnique,
})
