import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, DATE_DEFAULT, launch, geocode, matchCover } from './lib.mjs'

// 媒体覆盖分析: center (address or lng/lat) + radius -> bus lines / metro stations.
// Example:
//   node coverage.mjs --address "上海乐高乐园" --radius 1000

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const address = arg('--address')
const name = arg('--name', address || '自定义中心点')
let lng = arg('--lng') ? Number(arg('--lng')) : null
let lat = arg('--lat') ? Number(arg('--lat')) : null
const radius = Number(arg('--radius', 1000))
const date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const outDir = path.resolve(arg('--out', OUT))
const mediaTypes = (arg('--media', 'bus,metro')).split(',').map((s) => s.trim()).filter(Boolean)
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (!address && (lng == null || lat == null)) {
  console.error('用法: node coverage.mjs --address "上海乐高乐园" --radius 1000 或 --lng 121.104 --lat 30.88 --radius 1000')
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
    console.log('地理编码:', address, '->', lng, lat)
  }
  const center = { name, address: address || name, lng, lat }
  const data = await matchCover(page, center, radius, mediaTypes, 'all')
  const items = data.data || []
  const buses = items.filter((x) => x.mediaType === 'bus')
  const metros = items.filter((x) => x.mediaType === 'metro')
  const payload = {
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
  const safe = String(name).replace(/[^\w一-龥-]+/g, '_')
  const file = path.join(outDir, `coverage_${safe}_${radius}.json`)
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
  fs.writeFileSync(csvFile, '﻿' + [csvHeader, ...csvRows].map((r) => r.map(esc).join(',')).join('\r\n'), 'utf8')
  console.log(`覆盖结果: 共 ${items.length} 条（公交 ${buses.length} / 地铁 ${metros.length}）`)
  console.log('公交线路:', payload.summary.bus_lines.join(', ') || '无')
  console.log('地铁站:', payload.summary.metro_stations.join(', ') || '无')
  for (const x of buses.slice(0, 8)) console.log(`  bus ${x.lineName} 距离 ${Math.round(x.minDistance)}m`)
  for (const x of metros.slice(0, 8)) console.log(`  metro ${x.nearestStaName || '-'} (${x.lineName}) 距离 ${Math.round(x.minDistance)}m`)
  console.log('JSON:', file)
  console.log('CSV:', csvFile)
} catch (e) {
  console.error('COVERAGE_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
