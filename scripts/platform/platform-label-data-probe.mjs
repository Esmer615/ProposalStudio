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

async function postForm(url, body) {
  return await page.evaluate(async ({ url, body }) => {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
      body,
    })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url, body })
}

try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const third = await postForm('/label/queryThirdLabel', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel=' + encodeURIComponent('全部'))
  fs.writeFileSync(path.join(OUT, 'label_third_bus_all.json'), third.text, 'utf8')
  console.log('THIRD status:', third.status, 'bytes:', third.text.length)
  let data = null
  try { data = JSON.parse(third.text) } catch {}
  const items = Array.isArray(data) ? data : data?.data || []
  console.log('THIRD count:', items.length)
  console.log('THIRD sample:', JSON.stringify(items.slice(0, 8), null, 1).slice(0, 4000))
  const targets = items.filter((x) => ['01', '01路', '1001', '1002'].includes(String(x.thirdLabel)) || String(x.thirdLabel).includes('1001') || String(x.thirdLabel).includes('1002'))
  console.log('TARGETS:', JSON.stringify(targets.slice(0, 10), null, 1).slice(0, 4000))
  const pick = targets.length ? targets : items.slice(0, 2)
  for (const x of pick.slice(0, 3)) {
    const id = x.id
    const r = await postForm('/label/queryLabelData', 'labelId=' + encodeURIComponent(id) + '&dataMonth=202305')
    const f = path.join(OUT, `label_data_${id}_202305.json`)
    fs.writeFileSync(f, r.text, 'utf8')
    let d = null
    try { d = JSON.parse(r.text) } catch {}
    console.log('LABEL_DATA', id, x.thirdLabel, r.status, r.text.length, 'keys:', d ? Object.keys(d).slice(0, 30) : null)
    console.log('PREVIEW:', r.text.slice(0, 2500))
  }
} catch (e) {
  console.log('LABEL_PROBE_ERROR:', e.message)
}
await browser.close()
