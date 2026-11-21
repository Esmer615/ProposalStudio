import fs from 'node:fs'
import { BASE, STATE, launch, getPoiTypes, getSelectOptions } from './lib.mjs'

// 地址查询（定制查询）的选项发现（实时读取页面 select + POI 类型）：
//   node address_options.mjs

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/looseMultiQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  const range = await getSelectOptions(page, '#queryRange').catch(() => null)
  const isHD = await getSelectOptions(page, '#isHD').catch(() => null)
  const poiTypes = await getPoiTypes(page)

  console.log('查询方式: 地址查询 / POI查询（页面顶部单选）')
  console.log('查询时间: 2023-05（固定）')
  if (range) console.log('查询范围 queryRange:', range.options.map((o) => `${o.value}(${o.text})`).join(' / '))
  if (isHD) console.log('红豆线路 isHD:', isHD.options.map((o) => `${o.value}(${o.text})`).join(' / '))
  console.log(`POI 类型（/basekeyword/query）: ${poiTypes.length} 个`)
  console.log('  ' + poiTypes.map((x) => x.keyName).join(' / '))
} catch (e) {
  console.error('ADDRESS_OPTIONS_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
