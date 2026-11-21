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
  await page.goto('https://flairmedia.com.cn:38880/looseMultiQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const range = await page.locator('#queryRange').evaluate((e) => ({
    tag: e.tagName,
    options: Array.from(e.options || []).map((o) => ({ value: o.value, text: o.text })),
    html: e.outerHTML.slice(0, 1000),
  }))
  console.log('RANGE:', JSON.stringify(range, null, 1))
  const r = await page.evaluate(async () => {
    const resp = await fetch('/basekeyword/query?page=0&rows=0', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    return { status: resp.status, text: await resp.text() }
  })
  console.log('KEYWORD status', r.status, 'bytes', r.text.length)
  console.log('KEYWORD preview', r.text.slice(0, 3000))
} catch (e) {
  console.log('OPTIONS_PROBE_ERROR:', e.message)
}
await browser.close()
