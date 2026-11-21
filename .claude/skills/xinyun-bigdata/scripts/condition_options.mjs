import fs from 'node:fs'
import { BASE, STATE, launch, getConditionOptions } from './lib.mjs'

// 条件查询选项发现（实时）：
//   node condition_options.mjs
//   node condition_options.mjs --type 人群属性
//   node condition_options.mjs --type 人群属性 --subtype 年龄属性
//   node condition_options.mjs --keyword 20

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const type = arg('--type')
const subtype = arg('--subtype')
const keyword = arg('--keyword')
const limit = Number(arg('--limit', 80))

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  const rows = await getConditionOptions(page)

  // 分组概览：firstType / secondType / thirdType
  const groups = {}
  for (const r of rows) {
    const key = [r.firstType, r.secondType, r.thirdType].filter(Boolean).join(' / ')
    groups[key] = (groups[key] || 0) + 1
  }
  if (!type && !keyword) {
    console.log(`条件选项共 ${rows.length} 条，分组（前 80）:`)
    for (const [k, n] of Object.entries(groups).slice(0, limit)) console.log(`  ${k}  (${n})`)
    console.log('提示: 用 --type / --subtype / --keyword 过滤；年龄属性的“20岁以下”下拉值是 53/54/55/56。')
    process.exit(0)
  }

  let hits = rows
  if (type) hits = hits.filter((r) => String(r.firstType || '').includes(type))
  if (subtype) hits = hits.filter((r) => String(r.secondType || '').includes(subtype))
  if (keyword) {
    const k = String(keyword)
    hits = hits.filter((r) =>
      [r.firstType, r.secondType, r.thirdType, r.conditionName, r.conditionId, r.dataItem]
        .some((x) => String(x ?? '').includes(k))
    )
  }
  console.log(`匹配 ${hits.length} 条:`)
  for (const r of hits.slice(0, limit)) {
    console.log(
      `  id=${r.id}  ${r.firstType || ''} / ${r.secondType || ''} / ${r.thirdType || ''}`
      + `  name=${r.conditionName || ''}  conditionId=${r.conditionId || ''}  dataItem=${r.dataItem || ''}`
      + (r.minValue != null ? `  min=${r.minValue} max=${r.maxValue}` : '')
    )
  }
  if (hits.length > limit) console.log(`  ... 还有 ${hits.length - limit} 条`)
} catch (e) {
  console.error('CONDITION_OPTIONS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
