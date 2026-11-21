import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN', acceptDownloads: true, viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
const reqs = []
page.on('request', (r) => {
  if (r.url().includes('/exportIndicatorData') || r.url().includes('/downloadExcel')) {
    reqs.push({ url: r.url(), method: r.method(), postData: r.postData(), type: r.resourceType() })
  }
})
page.on('response', async (r) => {
  if (r.url().includes('/exportIndicatorData') || r.url().includes('/downloadExcel')) {
    let text = ''
    try { text = (await r.text()).slice(0, 4000) } catch {}
    reqs.push({ response: r.url(), status: r.status(), ct: r.headers()['content-type'], text })
  }
})
page.on('download', async (d) => {
  const f = path.join(OUT, 'ui_download_' + d.suggestedFilename())
  await d.saveAs(f).catch(() => {})
  console.log('DOWNLOAD:', d.suggestedFilename(), f)
})

try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(4000)
  const labels = await page.evaluate(async () => {
    const r = await fetch('/label/queryThirdLabel', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
      body: 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel=',
    })
    const arr = await r.json()
    const ids = ['6382', '6000', '6001']
    return arr.filter((x) => ids.includes(String(x.id)))
  })
  console.log('LABELS:', JSON.stringify(labels, null, 1).slice(0, 2000))
  const ids = labels.map((x) => String(x.id))
  await page.evaluate(({ labels, ids }) => {
    const w = window
    w.busiModel = w.busiModel || {}
    w.busiModel.labelIdNameMap = w.busiModel.labelIdNameMap || {}
    for (const l of labels) w.busiModel.labelIdNameMap[String(l.id)] = l
    w.jQuery('#queryDate').val('2023-05')
    w.busiModel.showLabel(ids)
  }, { labels, ids })
  await page.waitForTimeout(8000)
  const frame = page.frame({ name: 'infoFrame' })
  console.log('INFO_FRAME:', frame ? frame.url() : 'none')
  if (frame) {
    const body = await frame.locator('body').innerText().catch(() => '')
    console.log('INFO_BODY:', body.slice(0, 2500).replace(/\s+/g, ' '))
    const result = await frame.evaluate(() => {
      try { window.infoPageModel.exportExcel(); return 'called' } catch (e) { return String(e) }
    })
    console.log('EXPORT_CALL:', result)
  }
  await page.waitForTimeout(8000)
  console.log('EXPORT_NETWORK:', JSON.stringify(reqs, null, 2).slice(0, 10000))
  await page.screenshot({ path: 'screenshots/platform-export-ui.png', fullPage: false })
} catch (e) {
  console.log('EXPORT_UI_ERROR:', e.message)
}
await browser.close()
