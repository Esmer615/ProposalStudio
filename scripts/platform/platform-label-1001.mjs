import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')

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
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
      body,
    })
    return { status: r.status, text: await r.text() }
  }, { url, body })
}
try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2500)
  for (const [tag, body] of [
    ['bus_all', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel='],
    ['bus_Aplus', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel=' + encodeURIComponent('A+')],
    ['bus_Aplusplus', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel=' + encodeURIComponent('A++')],
  ]) {
    const r = await postForm('/label/queryThirdLabel', body)
    fs.writeFileSync(path.join(OUT, `third_${tag}.json`), r.text, 'utf8')
    let d = null
    try { d = JSON.parse(r.text) } catch {}
    const arr = Array.isArray(d) ? d : d?.data || []
    console.log(tag, 'status', r.status, 'bytes', r.text.length, 'count', Array.isArray(arr) ? arr.length : '?')
    if (Array.isArray(arr) && arr.length) {
      console.log(' first:', JSON.stringify(arr.slice(0, 3), null, 1).slice(0, 1200))
      const targets = arr.filter((x) => ['01', '01路', '1001', '1002'].includes(String(x.thirdLabel)))
      console.log(' targets:', JSON.stringify(targets, null, 1).slice(0, 2000))
      for (const x of targets.slice(0, 3)) {
        const lr = await postForm('/label/queryLabelData', 'labelId=' + encodeURIComponent(x.id) + '&dataMonth=202305')
        fs.writeFileSync(path.join(OUT, `label_data_${x.id}_202305.json`), lr.text, 'utf8')
        let ld = null
        try { ld = JSON.parse(lr.text) } catch {}
        console.log('  labelData', x.id, x.thirdLabel, lr.status, lr.text.length, ld ? Object.keys(ld) : null)
        console.log('  preview:', lr.text.slice(0, 1500))
      }
    }
  }
} catch (e) {
  console.log('PROBE_ERROR:', e.message)
}
await browser.close()
