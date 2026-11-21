import fs from 'node:fs'
import { BASE, STATE, launch, getLineTree, flattenTree } from './lib.mjs'

// AI线路选项发现（实时读取线路树/站点树）：
//   node ai_route_options.mjs --tree line
//   node ai_route_options.mjs --tree line --search 1001
//   node ai_route_options.mjs --tree station --search 人民广场

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const treeType = arg('--tree', 'line')
const search = arg('--search')
const limit = Number(arg('--limit', 80))

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  const url = treeType === 'station' ? '/busLineShowSolutionStation' : '/busLineShowSolution'
  await page.goto(BASE + url, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  const tree = await getLineTree(page, treeType)
  const flat = flattenTree(tree)

  if (!search) {
    console.log(`${treeType === 'station' ? '站点' : '线路'}树顶层分组：`)
    for (const g of tree) {
      const children = flattenTree(g.children || [])
      const leaf = children.filter((x) => (treeType === 'station' ? x.staName : x.lineName))
      console.log(`  ${g.name || '(未命名)'}：${leaf.length} 个${treeType === 'station' ? '站点' : '线路'}`)
    }
    console.log('提示: 加 --search <名称> 查具体节点；线路节点含 lineId/lineName/linePath。')
    process.exit(0)
  }

  const k = String(search).trim()
  const norm = (s) => String(s ?? '').replace(/路$/g, '').trim()
  const hits = flat.filter((x) =>
    treeType === 'station'
      ? (x.staName && (String(x.staName).includes(k) || norm(x.staName) === norm(k)))
      : (x.lineName && (String(x.lineName).includes(k) || norm(x.lineName) === norm(k)))
  )
  console.log(`匹配 ${hits.length} 个${treeType === 'station' ? '站点' : '线路'}：`)
  for (const x of hits.slice(0, limit)) {
    if (treeType === 'station') {
      console.log(`  ${x.staName}  staLocaltion=${x.staLocaltion || '-'}  lineName=${x.lineName || '-'}`)
    } else {
      console.log(`  ${x.lineName}  lineId=${x.lineId}  linePath=${x.linePath || '-'}`)
    }
  }
  if (hits.length > limit) console.log(`  ... 还有 ${hits.length - limit} 个`)
} catch (e) {
  console.error('AI_ROUTE_OPTIONS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
