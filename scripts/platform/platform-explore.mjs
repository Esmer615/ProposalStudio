import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT_DIR = path.join(ROOT, 'data', 'external')
const STATE = path.join(OUT_DIR, 'platform_storage.json')
fs.mkdirSync(OUT_DIR, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('missing platform_storage.json; run platform-login.mjs first')
  process.exit(2)
}

const LABELS = ['媒体查询', '组合查询', '自由查询', '条件查询', '定制查询', '媒体覆盖分析', 'AI线路', 'AI线路-站点']
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({
  storageState: STATE,
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 960 },
  locale: 'zh-CN',
  acceptDownloads: true,
})
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) {
    return route.continue({ url: u.replace('http://', 'https://') })
  }
  return route.continue()
})

let apiBodies = {}
page.on('response', async (resp) => {
  const req = resp.request()
  if (!['xhr', 'fetch'].includes(req.resourceType())) return
  const u = resp.url()
  if (!u.includes('flairmedia.com.cn:38880')) return
  if (/\.(js|css|png|jpg|jpeg|gif|svg|woff2?|mp4)(\?|$)/i.test(u)) return
  const ct = (resp.headers()['content-type'] || '').split(';')[0]
  try {
    const body = await resp.text()
    if (body.length > 1_500_000) return
    apiBodies[u] = { status: resp.status(), ct, body: body.slice(0, 300_000) }
  } catch {
    /* ignore binary */
  }
})
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message))

async function mainFrameInfo() {
  let frame = page.frames().find((f) => f.name() === 'mainFrame')
  if (!frame) {
    const frames = page.frames().filter((f) => f !== page.mainFrame())
    frame = frames[frames.length - 1]
  }
  if (!frame) return { url: null, body: '', inputs: [], buttons: [] }
  const body = await frame.locator('body').innerText().catch(() => '')
  const inputs = await frame
    .locator('input')
    .evaluateAll((els) =>
      els.map((e) => ({
        type: e.getAttribute('type'),
        id: e.getAttribute('id'),
        name: e.getAttribute('name'),
        placeholder: e.getAttribute('placeholder'),
        value: e.getAttribute('value'),
      }))
    )
    .catch(() => [])
  const buttons = await frame
    .locator('button, a, [role="button"]')
    .evaluateAll((els) =>
      els
        .map((e) => ({
          text: (e.innerText || '').trim(),
          href: e.getAttribute('href'),
          onclick: e.getAttribute('onclick'),
        }))
        .filter((x) => x.text || x.onclick || x.href)
        .slice(0, 80)
    )
    .catch(() => [])
  return { url: frame.url(), body: body.slice(0, 8000), inputs, buttons }
}

const result = {}
try {
  await page.goto('https://flairmedia.com.cn:38880/', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(5000)
  console.log('DASHBOARD URL:', page.url())
  const menuResp = Object.entries(apiBodies).find(([u]) => u.includes('/menu/queryMenuByUserId'))
  console.log('MENU API:', menuResp ? menuResp[0] : '(not captured)')
  console.log('FRAMES:', JSON.stringify(page.frames().map((f) => ({ name: f.name(), url: f.url() })), null, 2))

  for (const label of LABELS) {
    apiBodies = {}
    process.stdout.write(`\n=== ${label} ===\n`)
    const loc = page.getByText(label, { exact: true }).first()
    try {
      await loc.click({ timeout: 8000, force: true })
    } catch (e) {
      console.log('CLICK_SKIPPED:', e.message.split('\n')[0])
    }
    await page.waitForTimeout(4500)
    const info = await mainFrameInfo()
    console.log('FRAME URL:', info.url)
    console.log('BODY:', info.body.slice(0, 1200).replace(/\s+/g, ' '))
    console.log('INPUTS:', JSON.stringify(info.inputs.slice(0, 20)))
    console.log('BUTTONS:', JSON.stringify([...new Set(info.buttons.map((b) => b.text).filter(Boolean))].slice(0, 40)))
    console.log('APIS:', JSON.stringify(Object.keys(apiBodies).slice(0, 30), null, 2))
    const slug = label.replace(/[^\w一-龥]+/g, '_')
    await page.screenshot({ path: `screenshots/platform-${slug}.png`, fullPage: false }).catch(() => {})
    result[label] = {
      ...info,
      apis: Object.fromEntries(Object.entries(apiBodies).slice(0, 60)),
      screenshot: `web/screenshots/platform-${slug}.png`,
    }
  }

  fs.writeFileSync(path.join(OUT_DIR, 'platform_explore.json'), JSON.stringify(result, null, 2), 'utf8')
  console.log('\nEXPLORE_SAVED: data/external/platform_explore.json')
} catch (e) {
  console.log('EXPLORE_ERROR:', e.message)
}
await browser.close()
