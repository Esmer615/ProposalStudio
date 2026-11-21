import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN', acceptDownloads: true })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
const fields = {
  queryType: '1',
  indicatorType: 'coverPeoples,visitorsFlowrate,regionAttribute,crowdAge,crowdGender,crowdHouse,crowdIndividualConsumption,crowdPhone,crowdExtInfo',
  dataMonth: '202305',
  labelIds: '6382,6000,6001',
  gridIds: '',
  extOptions: JSON.stringify({ gridType: '500', underground: '0' }),
  fileName: '大数据洞察所选区域汇总值_2023-05_公交_测试组16',
}
try {
  await page.goto('https://flairmedia.com.cn:38880/infoPage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const r = await page.evaluate(async (fields) => {
    const resp = await fetch('/exportIndicatorData', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
      body: new URLSearchParams(fields).toString(),
    })
    return { status: resp.status, ct: resp.headers.get('content-type'), text: await resp.text() }
  }, fields)
  console.log('EXPORT status', r.status, 'ct', r.ct, 'bytes', r.text.length)
  console.log('EXPORT text', r.text.slice(0, 1500))
  let d = null
  try { d = JSON.parse(r.text) } catch {}
  if (d?.code === '0000' && d?.data) {
    const fp = encodeURI(encodeURI(String(d.data)))
    const fn = encodeURI(encodeURI(fields.fileName + '.xlsx'))
    const url = `https://flairmedia.com.cn:38880/downloadExcel?filePath=${fp}&excelType=1&fileName=${fn}`
    const dl = await context.request.get(url)
    const buf = await dl.body()
    const file = path.join(OUT, 'ui_export_1001_1002_202305.xlsx')
    fs.writeFileSync(file, buf)
    console.log('DOWNLOAD', dl.status(), dl.headers()['content-type'], buf.length, file)
  }
} catch (e) {
  console.log('EXPORT_PROBE_ERROR:', e.message)
}
await browser.close()
