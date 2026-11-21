import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const DATE = process.argv[2] || '202305'
const LABEL_IDS = (process.argv[3] || '6382,6000,6001').split(',').map((s) => s.trim()).filter(Boolean)
const INDICATORS = [
  'visitorsFlowrateAndcrowdSpeed',
  'circleCross',
  'regionAttribute',
  'crowdAge',
  'crowdGender',
  'crowdHouse',
  'crowdConsumption',
  'crowdPhoneNew',
]
const EXPORT_INDICATORS =
  'coverPeoples,visitorsFlowrate,regionAttribute,crowdAge,crowdGender,crowdHouse,crowdIndividualConsumption,crowdPhone,crowdExtInfo'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN', acceptDownloads: true })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
const DATA_URL = '/bbf8e41e454b47126290905525c69f7'

async function postForm(url, fields) {
  return await page.evaluate(async ({ url, fields }) => {
    const body = new URLSearchParams(fields).toString()
    const r = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
      body,
    })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url, fields })
}

try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2500)
  const extOptions = JSON.stringify({ gridType: '500', underground: '0' })
  const results = {}
  for (const ind of INDICATORS) {
    const r = await postForm(DATA_URL, {
      queryType: '1',
      indicatorType: ind,
      dataMonth: DATE,
      labelIds: LABEL_IDS.join(','),
      gridIds: '',
      extOptions,
    })
    const file = path.join(OUT, `indicator_${ind}_${DATE}.json`)
    fs.writeFileSync(file, r.text, 'utf8')
    let d = null
    try { d = JSON.parse(r.text) } catch {}
    results[ind] = { status: r.status, bytes: r.text.length, code: d?.code, dataType: Array.isArray(d?.data) ? 'array' : typeof d?.data }
    console.log(ind, 'status', r.status, 'bytes', r.text.length, 'code', d?.code, 'data', Array.isArray(d?.data) ? `array(${d.data.length})` : typeof d?.data)
    console.log('  preview:', r.text.slice(0, 1000).replace(/\s+/g, ' '))
  }
  fs.writeFileSync(path.join(OUT, `indicator_summary_${DATE}.json`), JSON.stringify(results, null, 2), 'utf8')

  // Export
  const exp = await postForm('/exportIndicatorData', {
    queryType: '1',
    indicatorType: EXPORT_INDICATORS,
    dataMonth: DATE,
    labelIds: LABEL_IDS.join(','),
    gridIds: '',
    extOptions,
  })
  console.log('EXPORT status', exp.status, 'bytes', exp.text.length)
  console.log('EXPORT preview', exp.text.slice(0, 1000))
  let expData = null
  try { expData = JSON.parse(exp.text) } catch {}
  if (expData?.code === '0000' && expData?.data) {
    const filePath = encodeURI(encodeURI(String(expData.data)))
    const fileName = encodeURI(encodeURI(`平台_组合查询_${LABEL_IDS.join('_')}_${DATE}.xlsx`))
    const url = `https://flairmedia.com.cn:38880/downloadExcel?filePath=${filePath}&excelType=1&fileName=${fileName}`
    const dl = await context.request.get(url)
    const buf = await dl.body()
    const file = path.join(OUT, `export_compare_${LABEL_IDS.join('_')}_${DATE}.xlsx`)
    fs.writeFileSync(file, buf)
    console.log('DOWNLOAD status', dl.status(), 'ct', dl.headers()['content-type'], 'bytes', buf.length, '->', file)
  }
} catch (e) {
  console.log('COMPARE_DATA_ERROR:', e.message)
}
await browser.close()
