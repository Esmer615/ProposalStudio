import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})

const captured = {}
page.on('request', (r) => {
  if (r.url().includes('/label/queryLabelByQueryCondition')) {
    captured.request = { url: r.url(), method: r.method(), postData: r.postData() }
  }
})
page.on('response', async (r) => {
  if (r.url().includes('/label/queryLabelByQueryCondition')) {
    try {
      captured.response = { status: r.status(), text: await r.text() }
    } catch {}
  }
})

try {
  await page.goto('https://flairmedia.com.cn:38880/conditionQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(7000)

  const selects = await page.locator('#queryPanel select').evaluateAll((els) =>
    els.map((e, idx) => ({
      idx,
      id: e.id,
      label: e.getAttribute('label'),
      options: Array.from(e.options || []).map((o) => ({ value: o.value, text: o.text })).slice(0, 12),
    }))
  )
  fs.writeFileSync(path.join(OUT, 'condition_selects.json'), JSON.stringify(selects, null, 2), 'utf8')
  console.log('SELECT_COUNT:', selects.length)
  console.log('SELECT_LABELS:', JSON.stringify(selects.map((s) => s.label)))

  const under20 = selects.find((s) => s.label && s.label.includes('20岁以下'))
  console.log('UNDER20_SELECT:', JSON.stringify(under20))
  if (!under20) throw new Error('20岁以下 select not found')

  const values = under20.options.map((o) => o.value).filter((v) => v !== '')
  await page.evaluate(({ label, values }) => {
    const $ = window.jQuery
    const sel = $('select[label="' + label + '"]')
    sel.combobox('setValues', values)
  }, { label: under20.label, values })
  console.log('SET_VALUES:', JSON.stringify(values))

  await page.evaluate(() => {
    const $ = window.jQuery
    $('#queryDate').val('2023-05')
    $('#queryDate').trigger('change')
  })
  await page.waitForTimeout(500)
  await page.locator('#queryButton').click({ force: true })
  await page.waitForTimeout(10000)

  console.log('REQUEST:', JSON.stringify(captured.request || null, null, 2))
  if (captured.response) {
    fs.writeFileSync(path.join(OUT, 'condition_label_response.json'), captured.response.text, 'utf8')
    console.log('RESPONSE status:', captured.response.status, 'bytes:', captured.response.text.length)
    try {
      const data = JSON.parse(captured.response.text)
      console.log('RESPONSE keys:', Object.keys(data))
      console.log('grids:', Array.isArray(data.grids) ? data.grids.length : typeof data.grids)
      console.log('labels:', Array.isArray(data.labels) ? data.labels.length : typeof data.labels)
      if (Array.isArray(data.grids) && data.grids.length) console.log('GRID_SAMPLE:', JSON.stringify(data.grids[0]).slice(0, 2000))
      if (Array.isArray(data.labels) && data.labels.length) console.log('LABEL_SAMPLE:', JSON.stringify(data.labels[0]).slice(0, 2000))
    } catch {
      console.log('RESPONSE preview:', captured.response.text.slice(0, 1500))
    }
  } else {
    console.log('RESPONSE: not captured')
  }
  await page.screenshot({ path: 'screenshots/platform-condition-result.png', fullPage: false })
  console.log('SCREENSHOT: web/screenshots/platform-condition-result.png')
} catch (e) {
  console.log('CONDITION_UI_ERROR:', e.message)
  await page.screenshot({ path: 'screenshots/platform-condition-error.png', fullPage: false }).catch(() => {})
}
await browser.close()
