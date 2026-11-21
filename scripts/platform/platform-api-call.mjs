import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const payload = {
  radius: Number(process.argv[3] || 1000),
  mediaTypes: ['bus', 'metro'],
  lineScope: 'all',
  centers: [
    {
      name: process.argv[2] || '上海乐高乐园',
      address: '上海市金山区枫泾镇',
      lng: 121.104,
      lat: 30.88,
    },
  ],
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({
  storageState: STATE,
  ignoreHTTPSErrors: true,
  locale: 'zh-CN',
})
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) {
    return route.continue({ url: u.replace('http://', 'https://') })
  }
  return route.continue()
})

try {
  await page.goto('https://flairmedia.com.cn:38880/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2500)
  const result = await page.evaluate(async ({ url, body }) => {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/javascript, */*; q=0.01',
      },
      body: JSON.stringify(body),
    })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url: '/baseInfoLine/matchCoverLines', body: payload })
  console.log('STATUS:', result.status, result.ct)
  const out = path.join(OUT, `match_${process.argv[2] || 'lego'}_${payload.radius}.json`)
  fs.writeFileSync(out, result.text, 'utf8')
  console.log('SAVED:', out, 'bytes:', result.text.length)
  let data
  try {
    data = JSON.parse(result.text)
  } catch {
    console.log('NOT_JSON:', result.text.slice(0, 800))
    process.exitCode = 1
  }
  if (data) {
    console.log('TOP_KEYS:', Object.keys(data))
    console.log('CODE:', data.code, 'MSG:', data.msg)
    const items = data.data
    console.log('ITEMS:', Array.isArray(items) ? items.length : typeof items)
    if (Array.isArray(items) && items.length) {
      console.log('ITEM_KEYS:', Object.keys(items[0]))
      console.log('FIRST:', JSON.stringify(items[0], null, 1).slice(0, 2500))
      console.log('LAST:', JSON.stringify(items[items.length - 1], null, 1).slice(0, 1200))
    }
  }
} catch (e) {
  console.log('API_CALL_ERROR:', e.message)
  process.exitCode = 1
}
await browser.close()
