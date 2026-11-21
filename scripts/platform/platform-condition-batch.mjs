import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const CONDITIONS = [
  { id: '53', label: '20岁以下 / 1万以下' },
  { id: '54', label: '20岁以下 / 1~5万' },
  { id: '55', label: '20岁以下 / 5~10万' },
  { id: '56', label: '20岁以下 / 10万以上' },
]
const MONTHS = ['202305', '202307']

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN' })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
await page.goto('https://flairmedia.com.cn:38880/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForTimeout(3500)

const manifest = []
for (const c of CONDITIONS) {
  for (const month of MONTHS) {
    try {
      const r = await page.evaluate(async ({ condition, month }) => {
        const resp = await fetch('/label/queryLabelByQueryCondition', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            Accept: 'application/json, text/javascript, */*; q=0.01',
          },
          body: 'queryCondition=' + encodeURIComponent(condition) + '&dataMonth=' + encodeURIComponent(month),
        })
        return { status: resp.status, ct: resp.headers.get('content-type'), text: await resp.text() }
      }, { condition: c.id, month })
      const file = path.join(OUT, `condition_${c.id}_${month}.json`)
      fs.writeFileSync(file, r.text, 'utf8')
      let data = null
      try { data = JSON.parse(r.text) } catch {}
      const summary = {
        condition: c.id,
        conditionLabel: c.label,
        month,
        status: r.status,
        bytes: r.text.length,
        grids: data && Array.isArray(data.grids) ? data.grids.length : null,
        labels: data && Array.isArray(data.labels) ? data.labels.length : null,
        file: path.relative(ROOT, file),
        fetchedAt: new Date().toISOString(),
      }
      manifest.push(summary)
      console.log(JSON.stringify({ condition: c.id, month, status: r.status, bytes: r.text.length, grids: summary.grids, labels: summary.labels }))
    } catch (e) {
      console.log('ERR', c.id, month, e.message)
      manifest.push({ condition: c.id, month, error: e.message })
    }
    await page.waitForTimeout(250)
  }
}
fs.writeFileSync(path.join(OUT, 'condition_manifest.json'), JSON.stringify(manifest, null, 2), 'utf8')
console.log('MANIFEST:', path.join(OUT, 'condition_manifest.json'))
await browser.close()
