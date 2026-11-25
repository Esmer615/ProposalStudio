import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, launch, geocode, getPoiTypes } from './lib.mjs'

// 媒体覆盖分析页的“周边点位”分支：
//   node coverage_poi.mjs --address "上海乐高乐园" --radius 1500 --types "商场,幼儿园" --mode count --json
//   node coverage_poi.mjs --address "上海乐高乐园" --radius 1500 --types "商场,写字楼,小区" --mode detail --json

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const address = arg('--address')
const name = arg('--name', address || '自定义中心点')
let lng = arg('--lng') ? Number(arg('--lng')) : null
let lat = arg('--lat') ? Number(arg('--lat')) : null
const radius = Number(arg('--radius', 1500))
const requestedTypes = (arg('--types', '商场,写字楼,小区')).split(',').map((s) => s.trim()).filter(Boolean)
const mode = arg('--mode', 'count')
const maxPage = Number(arg('--max-page', 1))
const outDir = path.resolve(arg('--out', OUT))
const jsonMode = process.argv.includes('--json')
const force = process.argv.includes('--force')
fs.mkdirSync(outDir, { recursive: true })

if (!address && (lng == null || lat == null)) {
  console.error('用法: node coverage_poi.mjs --address "上海乐高乐园" --radius 1500 --types "商场,幼儿园" --mode detail --json')
  process.exit(2)
}

const safe = String(name).replace(/[^\w一-龥-]+/g, '_')
const typesTag = requestedTypes.join('_').replace(/[^\w一-龥-]+/g, '_')
const jsonFile = path.join(outDir, `coverage_poi_${safe}_${radius}_${mode}_${typesTag}.json`)

if (!force && fs.existsSync(jsonFile)) {
  try {
    const cached = JSON.parse(fs.readFileSync(jsonFile, 'utf8'))
    const ts = Date.parse(cached?.meta?.fetchedAt || '')
    if (cached?.ok && Number.isFinite(ts) && (Date.now() - ts) < 24 * 3600 * 1000) {
      cached.cached = true
      if (jsonMode) console.log(JSON.stringify(cached))
      else console.log(`周边点位(缓存/${mode}): ${cached.meta.center.name} 共 ${cached.items?.length ?? 0} 条`)
      process.exit(0)
    }
  } catch {}
}

if (!fs.existsSync(STATE)) {
  const err = { ok: false, status: 'skipped', reason: 'MANUAL_LOGIN_REQUIRED', message: '缺少登录会话' }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  if (address && (lng == null || lat == null)) {
    const g = await geocode(page, address)
    lng = g.lng
    lat = g.lat
    if (!jsonMode) console.log('地理编码:', address, '->', lng, lat)
  }
  const poiTypes = await getPoiTypes(page)
  const valid = new Set(poiTypes.map((x) => x.keyName))
  const types = requestedTypes.filter((t) => valid.has(t))
  const dropped = requestedTypes.filter((t) => !valid.has(t))
  if (!types.length) {
    throw new Error(`无有效点位类型；可用类型: ${[...valid].join(' / ')}`)
  }
  const center = { name, address: address || name, lng, lat }
  const reqBody = {
    searchMode: 'circle',
    keywords: types,
    maxPage,
    radius,
    centers: [center],
  }
  const url = mode === 'detail' ? '/nearby/detail' : '/nearby/count'
  const r = await page.evaluate(async ({ url, reqBody }) => {
    const resp = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(reqBody),
    })
    return { status: resp.status, text: await resp.text() }
  }, { url, reqBody })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`周边点位查询失败（${r.status}）：${r.text.slice(0, 300)}`)
  const result = data.data || []

  const counts = {}
  const items = []
  if (mode === 'count') {
    for (const x of result) {
      counts[x.keyword] = Number(x.total || 0)
    }
  } else {
    for (const x of result) {
      const kw = x.keyword || 'POI'
      counts[kw] = (counts[kw] || 0) + 1
      items.push({
        keyword: kw,
        name: x.name || '',
        subjectName: x.subjectName || x.name || '',
        address: x.address || '',
        distance: Math.round(Number(x.distance || 0)),
        region: x.region || x.area || '',
        lng: Number(x.lng),
        lat: Number(x.lat),
      })
    }
  }

  const outPayload = {
    ok: true,
    cached: false,
    meta: {
      source: '新云传媒大数据可视化平台',
      api: url,
      platform: BASE,
      center,
      radius,
      mode,
      types,
      droppedTypes: dropped,
      fetchedAt: new Date().toISOString(),
    },
    counts,
    total: mode === 'count'
      ? Object.values(counts).reduce((a, b) => a + b, 0)
      : items.length,
    items: items.slice(0, 120),
  }
  fs.writeFileSync(jsonFile, JSON.stringify(outPayload, null, 2), 'utf8')

  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  let header
  let rows
  if (mode === 'count') {
    header = ['检索模式', '中心点名称', '中心点经度', '中心点纬度', '行政区', '搜索半径', '点位类型', '检索数量']
    rows = result.map((x) => [
      '圆形', center.name, center.lng, center.lat,
      x.region || x.area || '', radius, x.keyword, x.total,
    ])
  } else {
    header = ['检索模式', '类型', '名称', '主体名称', '合并数量', '地址', '距离中心点', '中心点', '行政区', '经度', '纬度']
    rows = result.map((x) => [
      '圆形', x.keyword, x.name, x.subjectName || x.name, x.mergeCount || 1,
      x.address, x.distance, center.name, x.region || x.area || '', x.lng, x.lat,
    ])
  }
  const csvFile = path.join(outDir, `coverage_poi_${safe}_${radius}_${mode}.csv`)
  fs.writeFileSync(csvFile, '\ufeff' + [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n'), 'utf8')

  if (jsonMode) {
    console.log(JSON.stringify(outPayload))
  } else {
    console.log(`周边点位（${mode}）: ${center.name} 半径 ${radius}m 类型 ${types.join('/')}`)
    if (mode === 'count') {
      for (const x of result) console.log(`  ${x.keyword}: ${x.total}`)
    } else {
      for (const x of result.slice(0, 15)) console.log(`  ${x.keyword} | ${x.name} | ${x.address || ''} | ${Math.round(x.distance || 0)}m`)
    }
    console.log('JSON:', jsonFile)
    console.log('CSV:', csvFile)
  }
} catch (e) {
  if (jsonMode) console.log(JSON.stringify({ ok: false, error: 'COVERAGE_POI_ERROR', message: e.message }))
  else console.error('COVERAGE_POI_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
