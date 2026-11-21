import fs from 'node:fs'
import { BASE, STATE, launch, getPoiTypes, getSelectOptions } from './lib.mjs'

// 媒体覆盖分析的选项发现（实时读取页面 select + 后端 POI 类型）：
//   node coverage_options.mjs

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  const nearRange = await getSelectOptions(page, '#queryRange').catch(() => null)
  const coverRange = await getSelectOptions(page, '#lineMatchRange').catch(() => null)
  const poiTypes = await getPoiTypes(page)

  console.log('查询内容 queryBizMode:')
  console.log('  poi  = 周边点位')
  console.log('  line = 覆盖媒体')
  console.log('检索范围 poiRangeMode:')
  console.log('  circle  = 圆形（中心点 + 半径）')
  console.log('  region  = 行政区')
  console.log('  polygon = 多边形')
  console.log('覆盖媒体中心来源 coverCenterSource:')
  console.log('  poi    = 使用已查询点位')
  console.log('  manual = 手动输入地址/坐标')
  console.log('媒体类型 coverMediaType: bus / metro')
  console.log('线路范围 coverLineScope: self = 仅新云媒体；all = 全部')
  if (nearRange) console.log('周边点位搜索半径 queryRange:', nearRange.options.map((o) => o.value).join(' / '))
  if (coverRange) console.log('覆盖半径 lineMatchRange:', coverRange.options.map((o) => o.value).join(' / '))
  console.log(`POI 类型（/basekeyword/query）: ${poiTypes.length} 个`)
  console.log('  ' + poiTypes.map((x) => x.keyName).join(' / '))
} catch (e) {
  console.error('COVERAGE_OPTIONS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
