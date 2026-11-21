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
  exportExcel,
  launch,
} from './lib.mjs'

// Usage:
//   node query.mjs --media 公交 --labels "01路,1001,1002" [--date 202305] [--out DIR] [--export]
// The query time is fixed to 2023-05 (202305); the platform has no 2023-07 data.

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const labelsArg = arg('--labels')
const media = arg('--media', '公交')
let date = arg('--date', DATE_DEFAULT).replace(/-/g, '')
const outDir = path.resolve(arg('--out', OUT))
const doExport = process.argv.includes('--export')

if (!labelsArg) {
  console.error('用法: node query.mjs --media 公交 --labels "01路,1001,1002" [--date 202305] [--out DIR] [--export]')
  process.exit(2)
}
if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (date !== DATE_DEFAULT) {
  console.warn(`[warn] 平台目前只有 ${DATE_DEFAULT}（2023-05）数据；${date} 可能返回空。`)
}
const tags = labelsArg.split(',').map((s) => s.trim()).filter(Boolean)
fs.mkdirSync(outDir, { recursive: true })

const { browser, context, page } = await launch({ headless: true, storageState: STATE, acceptDownloads: true })
try {
  await page.goto(BASE + '/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2500)

  const all = await getThirdLabels(page, media)
  const { labels, missing } = matchLabels(all, tags)
  if (missing.length) {
    const suggestions = all
      .filter((x) => missing.some((m) => String(x.thirdLabel).includes(m) || String(x.ext1 || '').includes(m)))
      .slice(0, 20)
      .map((x) => `${x.thirdLabel} (id=${x.id})`)
    console.error(`未找到标签: ${missing.join(', ')}`)
    if (suggestions.length) console.error('可能匹配: ' + suggestions.join(' | '))
    process.exit(3)
  }

  const ids = labels.map((x) => String(x.id))
  console.log('匹配标签:')
  for (const x of labels) {
    console.log(`  ${x.firstLabel}-${x.secondLabel}-${x.thirdLabel}  id=${x.id}  ${x.ext4 || ''}`)
  }

  const indicators = await fetchIndicators(page, ids, date)
  const summary = buildSummary(indicators)
  const payload = {
    meta: {
      source: '新云传媒大数据可视化平台',
      platform: BASE,
      queryPath: '/comparePage',
      date,
      media,
      requestedTags: tags,
      labels: labels.map(describeLabel),
      fetchedAt: new Date().toISOString(),
      note: '平台仅提供 2023-05 数据；标签/数据来自比赛测试账号，仅用于本项目。',
    },
    summary,
    indicators: Object.fromEntries(
      Object.entries(indicators).map(([k, v]) => [k, { status: v.status, code: v.code, data: v.data, rawText: v.rawText }])
    ),
  }
  const baseName = `compare_${ids.join('_')}_${date}`
  const jsonFile = path.join(outDir, `${baseName}.json`)
  fs.writeFileSync(jsonFile, JSON.stringify(payload, null, 2), 'utf8')

  console.log('\n汇总:')
  console.log(`  20岁以下: ${summary.under20_pct ?? '-'}%`)
  console.log(`  20~30岁: ${summary.age_20_30_pct ?? '-'}% | 30~40岁: ${summary.age_30_40_pct ?? '-'}% | 40~50岁: ${summary.age_40_50_pct ?? '-'}% | 50岁以上: ${summary.age_50plus_pct ?? '-'}%`)
  console.log(`  男性: ${summary.male_pct ?? '-'}% | 女性: ${summary.female_pct ?? '-'}%`)
  console.log(`  房产(%): 无房 ${summary.house_pct.zero ?? '-'} | 一套 ${summary.house_pct.one ?? '-'} | 二套 ${summary.house_pct.two ?? '-'} | 多套 ${summary.house_pct.more ?? '-'}`)
  console.log(`  手机品牌 Top: ${summary.top_phones.map((x) => `${x.phone_name}:${x.num}`).join(' / ')}`)
  console.log(`  时段人流点: ${summary.flow_points} (非零 ${summary.flow_nonzero_points}, 最大 ${summary.flow_max ?? '-'})`)
  console.log('JSON:', jsonFile)

  if (doExport) {
    try {
      const exp = await exportExcel(context, ids, date, outDir, `大数据洞察_${ids.join('_')}_${date}`)
      console.log('EXCEL:', exp.path, `(${exp.bytes} bytes)`)
    } catch (e) {
      console.log('EXCEL_EXPORT_FAILED:', e.message)
    }
  }
} finally {
  await browser.close()
}
