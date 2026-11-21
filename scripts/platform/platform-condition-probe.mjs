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
const api = {}
page.on('response', async (r) => {
  const u = r.url()
  if (!u.includes('flairmedia.com.cn:38880')) return
  if (!['xhr', 'fetch'].includes(r.request().resourceType())) return
  const ct = (r.headers()['content-type'] || '').split(';')[0]
  if (!ct.includes('json')) return
  try {
    const t = await r.text()
    if (t.length < 2_000_000) api[u] = { status: r.status(), body: t.slice(0, 500_000) }
  } catch {}
})

try {
  await page.goto('https://flairmedia.com.cn:38880/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(5000)

  const options = await page.evaluate(async () => {
    const r = await fetch('/conditionQuery/queryAllCondition', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
      body: '',
    })
    const t = await r.text()
    return { status: r.status, text: t }
  })
  fs.writeFileSync(path.join(OUT, 'condition_options_raw.json'), options.text, 'utf8')
  console.log('OPTIONS status:', options.status, 'bytes:', options.text.length)
  let data = null
  try { data = JSON.parse(options.text) } catch {}
  if (data) {
    console.log('OPTIONS keys:', Object.keys(data))
    console.log('OPTIONS preview:', JSON.stringify(data, null, 1).slice(0, 6000))
  }

  const selects = await page.locator('#queryPanel select').evaluateAll((els) =>
    els.map((e, idx) => ({
      idx,
      id: e.id,
      label: e.getAttribute('label'),
      name: e.getAttribute('name'),
      multiple: e.multiple,
      options: Array.from(e.options || []).slice(0, 12).map((o) => ({ value: o.value, text: o.text })),
    }))
  )
  console.log('SELECTS:', JSON.stringify(selects, null, 2).slice(0, 20000))

  const dateVal = await page.locator('#queryDate').inputValue().catch(() => '')
  console.log('queryDate default:', dateVal)

  // Try selecting 20岁以下 in the 年龄属性 select via EasyUI, set 2023-05, query.
  const ageSelect = page.locator('#queryPanel select[label="年龄属性"]')
  console.log('age select count:', await ageSelect.count())
  if (await ageSelect.count()) {
    const vals = await ageSelect.locator('option').evaluateAll((opts) => opts.map((o) => ({ value: o.value, text: o.text })))
    console.log('AGE OPTIONS:', JSON.stringify(vals))
    const under20 = vals.find((v) => v.text.includes('20岁以下') || v.text.includes('20以下'))
    if (under20) {
      await page.evaluate(({ value }) => {
        const $ = window.jQuery
        $('#queryPanel select[label="年龄属性"]').combobox('setValues', [value])
      }, { value: under20.value })
      console.log('selected age value:', under20.value, under20.text)
    }
  }
  await page.locator('#queryDate').fill('2023-05').catch(() => {})
  await page.waitForTimeout(500)
  await page.locator('#queryButton').click({ force: true }).catch((e) => console.log('query click error:', e.message.split('\n')[0]))
  await page.waitForTimeout(8000)

  const labelResp = Object.entries(api).find(([u]) => u.includes('/label/queryLabelByQueryCondition'))
  if (labelResp) {
    const [u, v] = labelResp
    fs.writeFileSync(path.join(OUT, 'condition_query_age_202305.json'), v.body, 'utf8')
    console.log('LABEL_RESPONSE:', u, v.status, v.body.length)
    console.log('LABEL_PREVIEW:', v.body.slice(0, 4000))
  } else {
    console.log('LABEL_RESPONSE: not captured')
  }
  console.log('API URLS:', JSON.stringify(Object.keys(api), null, 2))
  await page.screenshot({ path: 'screenshots/platform-condition.png', fullPage: false })
  console.log('SCREENSHOT: web/screenshots/platform-condition.png')
} catch (e) {
  console.log('CONDITION_ERROR:', e.message)
}
await browser.close()
