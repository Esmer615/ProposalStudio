import fs from 'node:fs'
import { BASE, STATE, launch, getFirstLabels, getSecondLabels, getThirdLabelsFor } from './lib.mjs'

// 组合查询选项发现（实时）：
//   node compare_options.mjs --first
//   node compare_options.mjs --first 公交
//   node compare_options.mjs --first 公交 --keyword 1001
//   node compare_options.mjs --first 公交 --second A+

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const first = arg('--first')
const second = arg('--second')
const keyword = arg('--keyword')
const limit = Number(arg('--limit', 40))

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)

  if (!first) {
    const rows = await getFirstLabels(page)
    console.log('一级标签:')
    for (const x of rows) console.log(`  ${x.firstLabel} (id=${x.id})`)
    process.exit(0)
  }

  if (second === undefined && !keyword) {
    const rows = await getSecondLabels(page, first)
    const names = [...new Set(rows.map((x) => x.secondLabel).filter(Boolean))]
    console.log(`二级标签（一级=${first}）: ${names.length} 个`)
    for (const n of names) console.log('  ' + n)
    console.log('提示：二级“全部”= 留空；带 --keyword 会直接列三级。')
    process.exit(0)
  }

  const rows = await getThirdLabelsFor(page, first, second ?? '')
  let hits = rows
  if (keyword) {
    const k = String(keyword).trim()
    const norm = (s) => String(s ?? '').replace(/路$/g, '').trim()
    hits = rows.filter((x) =>
      String(x.thirdLabel).includes(k) ||
      norm(x.thirdLabel) === norm(k) ||
      norm(x.ext1) === norm(k) ||
      String(x.ext1 || '').includes(k)
    )
  }
  console.log(`三级标签（一级=${first}, 二级=${second === undefined ? '全部' : (second || '全部')}）: 共 ${rows.length}，匹配 ${hits.length}`)
  for (const x of hits.slice(0, limit)) {
    console.log(`  ${x.secondLabel || '-'}-${x.thirdLabel}  id=${x.id}  ${x.ext4 || ''}  ext1=${x.ext1 || ''}`)
  }
  if (hits.length > limit) console.log(`  ... 还有 ${hits.length - limit} 条，用 --limit 调整`)
} catch (e) {
  console.error('COMPARE_OPTIONS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
