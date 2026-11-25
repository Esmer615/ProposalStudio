import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, DATE_DEFAULT, launch, geocode, matchCover } from './lib.mjs'

// 媒体覆盖分析: center (address or lng/lat) + radius -> bus lines / metro stations.
// Example:
//   node coverage.mjs --address "上海乐高乐园" --radius 1500 --json

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const address = arg('--address')
const name = arg('--name', address || '自定义中心点')
let lng = arg('--lng') ? Number(arg('--lng')) : null
let lat = arg('--lat') ? Number(arg('--lat')) : null
const radius = Number(arg('--radius', 1500))
const date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const outDir = path.resolve(arg('--out', OUT))
const mediaTypes = (arg('--media', 'bus,metro')).split(',').map((s) => s.trim()).filter(Boolean)
const jsonMode = process.argv.includes('--json')
const force = process.argv.includes('--force')
fs.mkdirSync(outDir, { recursive: true })

if (!address && (lng == null || lat == null)) {
  console.error('用法: node coverage.mjs --address "上海乐高乐园" --radius 1500 或 --lng 121.104 --lat 30.88 --radius 1500')
  process.exit(2)
}

const safe = String(name).replace(/[^\w一-龥-]+/g, '_')
const file = path.join(outDir, `coverage_${safe}_${radius}.json`)

// Reuse fresh cached file (< 24h) unless --force
if (!force && fs.existsSync(file)) {
  try {
    const cached = JSON.parse(fs.readFileSync(file, 'utf8'))
    const ts = Date.parse(cached?.meta?.fetchedAt || '')
    if (cached?.summary && Number.isFinite(ts) && (Date.now() - ts) < 24 * 3600 * 1000) {
      cached.cached = true
      if (jsonMode) {
        console.log(JSON.stringify(cached))
      } else {
        console.log(`覆盖结果(缓存): 共 ${cached.summary.total} 条（公交 ${cached.summary.bus} / 地铁 ${cached.summary.metro}）`)
        console.log('JSON:', file)
      }
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
  const center = { name, address: address || name, lng, lat }
  const data = await matchCover(page, center, radius, mediaTypes, 'all')
  const items = data.data || []
  const buses = items.filter((x) => x.mediaType === 'bus')
  const metros = items.filter((x) => x.mediaType === 'metro')
  const payload = {
    ok: true,
    cached: false,
    meta: {
      source: '新云传媒大数据可视化平台',
      api: '/baseInfoLine/matchCoverLines',
      platform: BASE,
      center,
      radius,
      mediaTypes,
      fetchedAt: new Date().toISOString(),
      note: '覆盖分析按中心点半径与系统线路轨迹计算；平台接口无 2023-05 日期参数，属当前轨迹快照。',
    },
    summary: {
      total: items.length,
      bus: buses.length,
      metro: metros.length,
      bus_lines: [...new Set(buses.map((x) => x.lineName))],
      metro_stations: [...new Set(metros.map((x) => x.nearestStaName).filter(Boolean))],
    },
    items,
  }
  fs.writeFileSync(file, JSON.stringify(payload, null, 2), 'utf8')

  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const csvHeader = ['mediaType', 'lineName', 'nearestStaName', 'lng', 'lat', 'minDistance', 'lineId', 'linePath']
  const csvRows = items.map((x) => [
    x.mediaType, x.lineName, x.nearestStaName || '',
    x.mediaType === 'metro' ? (x.nearestStaLng ?? x.nearestLng) : x.nearestLng,
    x.mediaType === 'metro' ? (x.nearestStaLat ?? x.nearestLat) : x.nearestLat,
    Math.round(x.minDistance || 0), x.lineId, x.linePath,
  ])
  const csvFile = path.join(outDir, `coverage_${safe}_${radius}.csv`)
  fs.writeFileSync(csvFile, '\ufeff' + [csvHeader, ...csvRows].map((r) => r.map(esc).join(',')).join('\r\n'), 'utf8')
  if (jsonMode) {
    console.log(JSON.stringify(payload))
  } else {
    console.log(`覆盖结果: 共 ${items.length} 条（公交 ${buses.length} / 地铁 ${metros.length}）`)
    console.log('公交线路:', payload.summary.bus_lines.join(', ') || '无')
    console.log('地铁站:', payload.summary.metro_stations.join(', ') || '无')
    for (const x of buses.slice(0, 8)) console.log(`  bus ${x.lineName} 距离 ${Math.round(x.minDistance)}m`)
    for (const x of metros.slice(0, 8)) console.log(`  metro ${x.nearestStaName || '-'} (${x.lineName}) 距离 ${Math.round(x.minDistance)}m`)
    console.log('JSON:', file)
    console.log('CSV:', csvFile)
  }
} catch (e) {
  if (jsonMode) console.log(JSON.stringify({ ok: false, error: 'COVERAGE_ERROR', message: e.message }))
  else console.error('COVERAGE_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
