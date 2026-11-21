import fs from 'node:fs'
import path from 'node:path'
import {
  BASE,
  STATE,
  OUT,
  DATE_DEFAULT,
  launch,
  geocode,
  circleBorder,
  queryLabelByBorder,
  exportExcel,
} from './lib.mjs'

// 地址查询（定制查询里的地址 + 范围 -> 覆盖媒体）。
// 流程：地址/坐标 + 半径 -> 命中媒体标签 -> 复用组合查询/条件查询的导出链路。
// 输出：大数据洞察_地址查询_<中心>_<半径>_<日期>.xls
// 不再保存 labels/sop JSON/CSV；只导出平台 Excel。

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const address = arg('--address')
let lng = arg('--lng') ? Number(arg('--lng')) : null
let lat = arg('--lat') ? Number(arg('--lat')) : null
const radius = Number(arg('--radius', 1000))
const date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const outDir = path.resolve(arg('--out', OUT))
const nameArg = arg('--name')
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (!address && (lng == null || lat == null)) {
  console.error('用法: node address.mjs --address "上海乐高乐园" --radius 1000 或 --lng 121.104 --lat 30.88 --radius 1000')
  process.exit(2)
}

const { browser, context, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/looseMultiQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  const centerName = address || '自定义坐标'
  if (address && (lng == null || lat == null)) {
    const g = await geocode(page, address)
    lng = g.lng
    lat = g.lat
    console.log('地理编码:', address, '->', lng, lat)
  }
  const border = circleBorder(lng, lat, radius)
  const data = await queryLabelByBorder(page, border, date)
  const labels = Array.isArray(data.labels) ? data.labels : []
  if (!labels.length) throw new Error('地址查询没有返回媒体标签，无法导出')
  console.log(`中心: ${centerName} (${lng}, ${lat}) 半径 ${radius}m`)
  console.log(`命中媒体: ${labels.length}`)

  const safe = String(centerName).replace(/[^\w一-龥-]+/g, '_')
  const fileName = nameArg || `大数据洞察_地址查询_${safe}_${radius}_${date}`
  const exp = await exportExcel(context, labels.map((x) => x.id), date, outDir, fileName)
  console.log('EXPORT:', exp.path, `(${exp.bytes} bytes)`)
} catch (e) {
  console.error('ADDRESS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
