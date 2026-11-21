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
function summary(tag, r) {
  let d = null
  try { d = JSON.parse(r.text) } catch {}
  const arr = Array.isArray(d) ? d : d?.data || []
  console.log(tag, 'status', r.status, 'bytes', r.text.length, 'count', Array.isArray(arr) ? arr.length : '?')
  console.log(' sample', JSON.stringify(Array.isArray(arr) ? arr.slice(0, 6) : d, null, 1).slice(0, 2500))
  return arr
}
try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const variants = [
    ['ALL_BASE_COMPARE', '/label/queryThirdLabel', 'firstLabel=&secondLabel=&baseCompare=1'],
    ['BUS_BASE_COMPARE', '/label/queryThirdLabel', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel=&baseCompare=1'],
    ['FIRST', '/label/queryFirstLabel', ''],
    ['SECOND_BUS', '/label/querySecondLabel', 'firstLabel=' + encodeURIComponent('公交')],
    ['THIRD_BUS_EMPTY_SECOND', '/label/queryThirdLabel', 'firstLabel=' + encodeURIComponent('公交') + '&secondLabel='],
  ]
  for (const [tag, url, body] of variants) {
    const r = await postForm(url, body)
    const arr = summary(tag, r)
    fs.writeFileSync(path.join(OUT, `tags_${tag}.json`), r.text, 'utf8')
    if (Array.isArray(arr)) {
      const target = arr.filter((x) => String(x.thirdLabel) === '1001' || String(x.thirdLabel) === '1002' || String(x.thirdLabel) === '01' || String(x.thirdLabel) === '01路' || String(x.lineName || '') === '1001')
      if (target.length) console.log(' TARGETS', JSON.stringify(target.slice(0, 6), null, 1).slice(0, 2500))
    }
  }
} catch (e) {
  console.log('TAGS_PROBE_ERROR:', e.message)
}
await browser.close()
