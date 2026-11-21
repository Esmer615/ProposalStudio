import { chromium } from '@playwright/test'
import path from 'node:path'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN' })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
try {
  await page.goto('https://flairmedia.com.cn:38880/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  const payload = {
    searchMode: 'circle',
    keywords: ['商场', '幼儿园'],
    maxPage: 1,
    radius: 1000,
    centers: [{ name: '上海乐高乐园', address: '上海乐高乐园', lng: 121.10782876001737, lat: 30.89309082539151 }],
  }
  for (const url of ['/nearby/count', '/nearby/detail']) {
    const r = await page.evaluate(async ({ url, payload }) => {
      const resp = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(payload) })
      return { status: resp.status, text: await resp.text() }
    }, { url, payload })
    console.log(url, 'status', r.status, 'bytes', r.text.length)
    console.log(r.text.slice(0, 2000))
  }
} catch (e) {
  console.log('POI_PROBE_ERROR:', e.message)
}
await browser.close()
