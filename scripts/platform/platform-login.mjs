import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const CRED = path.join(ROOT, 'scripts', '.credentials')
const OUT_DIR = path.join(ROOT, 'data', 'external')
fs.mkdirSync(OUT_DIR, { recursive: true })

function loadCredentials() {
  // scripts/.credentials: line1 = user, line2 = password. Never print them.
  const lines = fs.readFileSync(CRED, 'utf8').split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
  if (lines.length < 2) throw new Error('scripts/.credentials 需要两行：用户名、密码')
  return { user: lines[0], pass: lines[1] }
}

const cred = loadCredentials()
console.log('credentials loaded (values hidden)')
const browser = await chromium.launch({ channel: 'chrome', headless: false })
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 960 },
  locale: 'zh-CN',
})
const page = await context.newPage()
const network = []
page.on('request', (r) => {
  if (['xhr', 'fetch', 'document'].includes(r.resourceType())) {
    const u = r.url()
    if (!/\.(js|css|png|jpg|jpeg|gif|svg|woff2?|mp4)(\?|$)/i.test(u)) {
      network.push(`${r.method()} ${u}`)
    }
  }
})
page.on('response', (r) => {
  const u = r.url()
  if (['xhr', 'fetch', 'document'].includes(r.request().resourceType()) && !/\.(js|css|png|jpg|jpeg|gif|svg|woff2?|mp4)(\?|$)/i.test(u)) {
    const ct = (r.headers()['content-type'] || '').split(';')[0]
    network.push(`  -> ${r.status()} ${ct} ${u}`)
  }
})
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message))

// Fix the nginx http->https redirect on port 38880.
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) {
    return route.continue({ url: u.replace('http://', 'https://') })
  }
  return route.continue()
})

try {
  await page.goto('https://flairmedia.com.cn:38880/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)

  // EasyUI visible inputs
  const userInput = page.locator('input[placeholder="请输入用户名/手机号"]').first()
  const passInput = page.locator('input[placeholder="请输入密码"]').first()
  const capInput = page.locator('input[placeholder="验证码"]').first()
  await userInput.fill(cred.user)
  await passInput.fill(cred.pass)
  await capInput.focus()
  console.log('LOGIN_PAGE_READY: 请在打开的 Chrome 中输入验证码并点击“登录”')
  console.log('WAITING_FOR_LOGIN (最多 5 分钟) ...')

  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 300000 })
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {})
  await page.waitForTimeout(2500)

  console.log('LOGIN_OK URL:', page.url())
  console.log('TITLE:', await page.title())

  const statePath = path.join(OUT_DIR, 'platform_storage.json')
  await context.storageState({ path: statePath })
  console.log('SESSION_SAVED:', statePath)

  const body = await page.locator('body').innerText().catch(() => '')
  console.log('BODY_HEAD:', body.slice(0, 3000))

  const links = await page.locator('a').evaluateAll((els) =>
    els
      .map((e) => ({ text: (e.innerText || '').trim(), href: e.getAttribute('href'), onclick: e.getAttribute('onclick') }))
      .filter((x) => x.text || x.href)
      .slice(0, 120)
  )
  console.log('LINKS:', JSON.stringify(links, null, 2))

  const iframes = await page.locator('iframe').evaluateAll((els) =>
    els.map((e) => ({ src: e.getAttribute('src'), id: e.id, name: e.getAttribute('name') }))
  )
  console.log('IFRAMES:', JSON.stringify(iframes, null, 2))

  const ls = await page.evaluate(() => Object.keys(localStorage))
  const ss = await page.evaluate(() => Object.keys(sessionStorage))
  console.log('localStorage:', JSON.stringify(ls), 'sessionStorage:', JSON.stringify(ss))

  await page.screenshot({ path: 'screenshots/platform-dashboard.png', fullPage: true })
  console.log('SCREENSHOT: web/screenshots/platform-dashboard.png')

  const meta = {
    url: page.url(),
    title: await page.title(),
    body: body.slice(0, 8000),
    links,
    iframes,
    localStorage: ls,
    sessionStorage: ss,
    network: [...new Set(network)].slice(0, 300),
    savedAt: new Date().toISOString(),
  }
  fs.writeFileSync(path.join(OUT_DIR, 'platform_dashboard_meta.json'), JSON.stringify(meta, null, 2), 'utf8')
  console.log('META_SAVED: data/external/platform_dashboard_meta.json')
} catch (e) {
  console.log('LOGIN_ERROR:', e.message)
  await page.screenshot({ path: 'screenshots/platform-login-error.png', fullPage: false }).catch(() => {})
  console.log('SCREENSHOT: web/screenshots/platform-login-error.png')
}
console.log('NETWORK:')
console.log([...new Set(network)].slice(0, 120).join('\n'))
// Leave the browser open briefly so the user can see the result, then close.
await page.waitForTimeout(3000)
await browser.close()
