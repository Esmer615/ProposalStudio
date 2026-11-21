import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN' })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})

async function call(condition, month) {
  return await page.evaluate(async ({ condition, month }) => {
    const r = await fetch('/label/queryLabelByQueryCondition', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/javascript, */*; q=0.01',
      },
      body: 'queryCondition=' + encodeURIComponent(condition) + '&dataMonth=' + encodeURIComponent(month),
    })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { condition, month })
}

try {
  await page.goto('https://flairmedia.com.cn:38880/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(4000)
  const results = []
  for (const condition of ['53', '54', '55', '56']) {
    for (const month of ['202305']) {
      const r = await call(condition, month)
      const file = path.join(OUT, `condition_${condition}_${month}.json`)
      fs.writeFileSync(file, r.text, 'utf8')
      let data = null
      try { data = JSON.parse(r.text) } catch {}
      const summary = {
        condition, month, status: r.status, ct: r.ct, bytes: r.text.length,
        keys: data ? Object.keys(data) : null,
        grids: data && Array.isArray(data.grids) ? data.grids.length : null,
        labels: data && Array.isArray(data.labels) ? data.labels.length : null,
        preview: r.text.slice(0, 600),
      }
      results.push(summary)
      console.log(JSON.stringify(summary))
      if (data && Array.isArray(data.grids) && data.grids.length) console.log(' GRID_SAMPLE', JSON.stringify(data.grids[0]).slice(0, 1200))
      if (data && Array.isArray(data.labels) && data.labels.length) console.log(' LABEL_SAMPLE', JSON.stringify(data.labels[0]).slice(0, 1200))
    }
  }
  fs.writeFileSync(path.join(OUT, 'condition_fetch_manifest.json'), JSON.stringify(results, null, 2), 'utf8')
  console.log('MANIFEST: data/external/platform/condition_fetch_manifest.json')
} catch (e) {
  console.log('CONDITION_FETCH_ERROR:', e.message)
}
await browser.close()
