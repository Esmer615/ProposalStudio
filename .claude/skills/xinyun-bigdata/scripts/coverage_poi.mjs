import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, launch, geocode, getPoiTypes } from './lib.mjs'

// 媒体覆盖分析页的“周边点位”分支：
//   node coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场,幼儿园" --mode count
//   node coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场" --mode detail
// 输出与平台“导出点位”按钮同格式的 CSV；不再保存 JSON/坐标串。

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const address = arg('--address')
const name = arg('--name', address || '自定义中心点')
let lng = arg('--lng') ? Number(arg('--lng')) : null
let lat = arg('--lat') ? Number(arg('--lat')) : null
const radius = Number(arg('--radius', 1000))
const types = (arg('--types', '商场')).split(',').map((s) => s.trim()).filter(Boolean)
const mode = arg('--mode', 'count')
const maxPage = Number(arg('--max-page', 1))
const outDir = path.resolve(arg('--out', OUT))
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (!address && (lng == null || lat == null)) {
  console.error('用法: node coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场,幼儿园" --mode count')
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
  const poiTypes = await getPoiTypes(page)
  const valid = new Set(poiTypes.map((x) => x.keyName))
  const bad = types.filter((t) => !valid.has(t))
  if (bad.length) {
    console.error('未知点位类型:', bad.join(', '))
    console.error('可用类型:', [...valid].join(' / '))
    process.exit(3)
  }
  const center = { name, address: address || name, lng, lat }
  const payload = {
    searchMode: 'circle',
    keywords: types,
    maxPage,
    radius,
    centers: [center],
  }
  const url = mode === 'detail' ? '/nearby/detail' : '/nearby/count'
  const r = await page.evaluate(async ({ url, payload }) => {
    const resp = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
    })
    return { status: resp.status, text: await resp.text() }
  }, { url, payload })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`周边点位查询失败（${r.status}）：${r.text.slice(0, 300)}`)
  const result = data.data || []

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
  const safe = String(name).replace(/[^\w一-龥-]+/g, '_')
  const csvFile = path.join(outDir, `coverage_poi_${safe}_${radius}_${mode}.csv`)
  fs.writeFileSync(csvFile, '﻿' + [header, ...rows].map((r) => r.map(esc).join(',')).join('\r\n'), 'utf8')

  console.log(`周边点位（${mode}）: ${center.name} 半径 ${radius}m 类型 ${types.join('/')}`)
  if (mode === 'count') {
    for (const x of result) console.log(`  ${x.keyword}: ${x.total}`)
  } else {
    for (const x of result) console.log(`  ${x.keyword} | ${x.name} | ${x.address || ''} | ${Math.round(x.distance || 0)}m`)
  }
  console.log('CSV:', csvFile)
} catch (e) {
  console.error('COVERAGE_POI_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
