import { chromium } from '@playwright/test'
import path from 'node:path'

const url = process.argv[2]
if (!url) {
  console.error('usage: node platform-share-check.mjs <share-url>')
  process.exit(2)
}
const browser = await chromium.launch({ channel: 'chrome', headless: true })
// No storageState: simulate an external viewer without login.
const context = await browser.newContext({ ignoreHTTPSErrors: true, locale: 'zh-CN', viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()) })
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(8000)
  console.log('URL:', page.url())
  console.log('TITLE:', await page.title())
  const body = await page.locator('body').innerText().catch(() => '')
  console.log('BODY:', body.slice(0, 1000).replace(/\s+/g, ' '))
  console.log('CANVAS:', await page.locator('canvas').count())
  const png = path.join('screenshots', 'ai_share_external.png')
  await page.screenshot({ path: png, fullPage: false })
  console.log('SCREENSHOT:', png)
  console.log('ERRORS:', JSON.stringify(errors.slice(0, 10)))
} catch (e) {
  console.log('SHARE_CHECK_ERROR:', e.message)
}
await browser.close()
