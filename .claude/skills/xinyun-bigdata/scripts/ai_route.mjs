import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, launch, getLineTree, flattenTree, getLineJson } from './lib.mjs'

// AI线路 / AI线路-站点：只读取线路树与几何，不保存方案（不调用 /baseInfoWeb/saveWeb）。
// Examples:
//   node ai_route.mjs --line 1001
//   node ai_route.mjs --station 人民广场

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const lineArg = arg('--line')
const stationArg = arg('--station')
const outDir = path.resolve(arg('--out', OUT))
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (!lineArg && !stationArg) {
  console.error('用法: node ai_route.mjs --line 1001 或 --station 人民广场')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  if (lineArg) {
    await page.goto(BASE + '/busLineShowSolution', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1500)
    const tree = await getLineTree(page, 'line')
    const flat = flattenTree(tree)
    const norm = (s) => String(s ?? '').replace(/路$/g, '').trim()
    const node = flat.find((n) => norm(n.lineName) === norm(lineArg) || norm(n.name) === norm(lineArg))
    if (!node) {
      const suggestions = flat
        .filter((n) => n.lineName && String(n.lineName).includes(norm(lineArg)))
        .slice(0, 20)
        .map((n) => `${n.lineName} (lineId=${n.lineId})`)
      console.error(`未找到线路 ${lineArg}`)
      if (suggestions.length) console.error('可能匹配: ' + suggestions.join(' | '))
      process.exit(3)
    }
    const linePath = node.linePath || node.path || node.lineName
    const geo = await getLineJson(page, linePath)
    const pathPoints = Array.isArray(geo?.path) ? geo.path : []
    // Platform /getLineJson returns {lng:<latitude>, lat:<longitude>} (swapped);
    // the page draws BMap.Point(mobile[i].lat, mobile[i].lng).
    const coords = pathPoints
      .map((p) => [Number(p.lat), Number(p.lng)])
      .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat))
    const lngs = coords.map((p) => p[0])
    const lats = coords.map((p) => p[1])
    const feature = {
      type: 'Feature',
      properties: {
        lineId: node.lineId,
        lineName: node.lineName,
        linePath: node.linePath,
        source: '新云大数据可视化平台 /baseInfoLine/getLineJson',
      },
      geometry: { type: 'LineString', coordinates: coords },
    }
    const geojson = {
      type: 'FeatureCollection',
      features: coords.length ? [feature] : [],
      meta: { platform: BASE, fetchedAt: new Date().toISOString(), note: '坐标已由平台 lng/lat 字段交换纠正为 [lng,lat]。' },
    }
    const file = path.join(outDir, `ai_line_${String(node.lineId || lineArg)}.geojson`)
    fs.writeFileSync(file, JSON.stringify(geojson, null, 2), 'utf8')
    console.log(`线路: ${node.lineName} (lineId=${node.lineId})`)
    console.log(`几何点: ${coords.length}`)
    if (coords.length) console.log(`bbox: lng ${Math.min(...lngs).toFixed(6)}..${Math.max(...lngs).toFixed(6)} / lat ${Math.min(...lats).toFixed(6)}..${Math.max(...lats).toFixed(6)}`)
    console.log('GeoJSON:', file)
  } else {
    await page.goto(BASE + '/busLineShowSolutionStation', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(1500)
    const tree = await getLineTree(page, 'station')
    const flat = flattenTree(tree)
    const node = flat.find((n) => n.staName && (String(n.staName) === stationArg || String(n.staName).includes(stationArg)))
    if (!node) {
      const suggestions = flat
        .filter((n) => n.staName && String(n.staName).includes(stationArg))
        .slice(0, 20)
        .map((n) => n.staName)
      console.error(`未找到站点 ${stationArg}`)
      if (suggestions.length) console.error('可能匹配: ' + suggestions.join(' | '))
      process.exit(3)
    }
    // staLocaltion is "lng,lat" per the platform's BMap.Point(ddd[0], ddd[1]).
    const raw = String(node.staLocaltion || '')
    const [lng, lat] = raw.split(',').map(Number)
    const payload = {
      meta: {
        source: '新云传媒大数据可视化平台',
        api: '/baseInfoLine/getTreeLine?type=station',
        platform: BASE,
        fetchedAt: new Date().toISOString(),
        note: '只读取站点树坐标，不保存方案。',
      },
      station: { staName: node.staName, staLocaltion: node.staLocaltion, lng, lat, lineName: node.lineName || null, lineId: node.lineId || null },
    }
    const file = path.join(outDir, `ai_station_${String(node.staName).replace(/[^\w一-龥-]+/g, '_')}.json`)
    fs.writeFileSync(file, JSON.stringify(payload, null, 2), 'utf8')
    console.log(`站点: ${node.staName} -> ${raw} (${lng}, ${lat})`)
    console.log('JSON:', file)
  }
} catch (e) {
  console.error('AI_ROUTE_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
