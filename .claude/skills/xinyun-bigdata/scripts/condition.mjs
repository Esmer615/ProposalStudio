import fs from 'node:fs'
import path from 'node:path'
import {
  BASE,
  STATE,
  OUT,
  DATE_DEFAULT,
  launch,
  queryCondition,
  exportExcel,
} from './lib.mjs'

// 条件查询（人群属性/区域属性）。
// 默认 condition=53：20岁以下 / 1万以下。
// 54=20岁以下/1~5万，55=5~10万，56=10万以上。
// 流程：查询条件 -> 取结果网格 id -> 调平台导出接口 -> 保存 Excel。
// 不再保存 grids/labels 原始数据；平台右侧 infoPage 的“导出”按钮走同一条链路。

const CONDITION_LABELS = {
  '17,53': '徐家汇商圈 + 20岁以下 / 1万以下',
  53: '20岁以下 / 1万以下',
  54: '20岁以下 / 1~5万',
  55: '20岁以下 / 5~10万',
  56: '20岁以下 / 10万以上',
}

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const condition = arg('--condition', '17,53')
const date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const outDir = path.resolve(arg('--out', OUT))
const nameArg = arg('--name')
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, context, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1800)
  const data = await queryCondition(page, condition, date)
  const labels = Array.isArray(data.labels) ? data.labels : []
  const labelIds = labels.map((x) => x.id).filter(Boolean)
  if (!labelIds.length) throw new Error('条件查询没有返回媒体标签，无法导出')
  const label = CONDITION_LABELS[condition] || '自定义 condition'
  console.log(`条件: ${label} (condition=${condition}, date=${date})`)
  console.log(`命中媒体: ${labels.length}`)

  const safeCondition = String(condition).replace(/[^\w一-龥-]+/g, '_')
  const fileName = nameArg || `大数据洞察_条件查询_${safeCondition}_${date}`
  const exp = await exportExcel(context, labelIds, date, outDir, fileName)
  console.log('EXPORT:', exp.path, `(${exp.bytes} bytes)`)
} catch (e) {
  console.error('CONDITION_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
