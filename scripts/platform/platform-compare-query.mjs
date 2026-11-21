import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({
  storageState: STATE,
  ignoreHTTPSErrors: true,
  locale: 'zh-CN',
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
})
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})

const api = []
page.on('response', async (r) => {
  const u = r.url()
  if (!u.includes('flairmedia.com.cn:38880')) return
  if (!['xhr', 'fetch'].includes(r.request().resourceType())) return
  const ct = (r.headers()['content-type'] || '').split(';')[0]
  try {
    const t = await r.text()
    api.push({ url: u, status: r.status(), ct, method: r.request().method(), postData: r.request().postData()?.slice(0, 1000), text: t.slice(0, 200000) })
  } catch {}
})
page.on('download', async (d) => {
  const file = path.join(OUT, 'compare_download_' + d.suggestedFilename())
  await d.saveAs(file).catch(() => {})
  console.log('DOWNLOAD:', d.suggestedFilename(), '->', file)
})

try {
  await page.goto('https://flairmedia.com.cn:38880/comparePage', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(6000)

  const combo = await page.evaluate(() => {
    const $ = window.jQuery
    const dump = (id) => {
      try {
        const data = $(id).combobox('getData') || []
        return data.slice(0, 30).map((x) => ({ value: x.value ?? x.id, text: x.text ?? x.conditionName ?? x.name }))
      } catch (e) {
        return String(e)
      }
    }
    return { first: dump('#firstLabel'), second: dump('#secondLabel'), third: dump('#thirdLabel') }
  })
  console.log('COMBO_FIRST:', JSON.stringify(combo.first))
  console.log('COMBO_SECOND:', JSON.stringify(combo.second))
  console.log('COMBO_THIRD:', JSON.stringify(combo.third))

  await page.evaluate(() => {
    const $ = window.jQuery
    $('#queryDate').val('2023-05')
    $('#queryDate').trigger('change')
    $('#firstLabel').combobox('setValue', '公交')
    $('#secondLabel').combobox('setValue', '全部')
    $('#thirdLabel').combobox('setValues', ['01路', '1001', '1002'])
    $('#addQuery').prop('checked', true)
  })
  await page.waitForTimeout(800)
  await page.locator('#queryButton').click({ force: true })
  await page.waitForTimeout(12000)

  const body = await page.locator('body').innerText().catch(() => '')
  console.log('BODY_AFTER_QUERY:', body.slice(0, 4000).replace(/\s+/g, ' '))
  await page.screenshot({ path: 'screenshots/platform-compare-result.png', fullPage: false })

  const interesting = api.filter((x) => !/\.(js|css|png|jpg|svg)/i.test(x.url))
  console.log('API_URLS:', JSON.stringify([...new Set(interesting.map((x) => `${x.status} ${x.method} ${x.url}`))], null, 2))
  for (const x of interesting) {
    if (/query|compare|label|media|flow|export|download|basecsv|basearea/i.test(x.url)) {
      console.log('---', x.status, x.method, x.url, x.ct, 'post:', x.postData)
      console.log('    ', x.text.slice(0, 1000).replace(/\s+/g, ' '))
    }
  }
  fs.writeFileSync(path.join(OUT, 'compare_query_api_dump.json'), JSON.stringify(interesting, null, 2), 'utf8')
  console.log('DUMP: data/external/platform/compare_query_api_dump.json')

  // Try export button if present
  const exportBtn = page.getByText('导出', { exact: true }).first()
  if (await exportBtn.count()) {
    console.log('CLICK_EXPORT')
    await exportBtn.click({ force: true }).catch((e) => console.log('export click error:', e.message.split('\n')[0]))
    await page.waitForTimeout(5000)
  } else {
    console.log('NO_EXPORT_BUTTON')
  }
} catch (e) {
  console.log('COMPARE_ERROR:', e.message)
  await page.screenshot({ path: 'screenshots/platform-compare-error.png', fullPage: false }).catch(() => {})
}
await browser.close()
