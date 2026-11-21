import { chromium } from '@playwright/test'

const url = 'https://flairmedia.com.cn:38880/'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 900 },
  locale: 'zh-CN',
})
const page = await context.newPage()
// The platform's Location header points to http://...:38880 although the port is HTTPS.
// Rewrite those mistaken redirects back to https for the probe.
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) {
    return route.continue({ url: u.replace('http://', 'https://') })
  }
  return route.continue()
})
const reqs = []
page.on('request', (r) => {
  const u = r.url()
  if (['xhr', 'fetch'].includes(r.resourceType()) || /api|login|captcha|auth|token/i.test(u)) {
    reqs.push(`${r.method()} ${u}`)
  }
})
page.on('response', async (r) => {
  const u = r.url()
  if (['xhr', 'fetch'].includes(r.request().resourceType()) || /api|login|captcha|auth|token/i.test(u)) {
    const ct = r.headers()['content-type'] || ''
    reqs.push(`  -> ${r.status()} ${r.request().method()} ${u} [${ct.split(';')[0]}]`)
  }
})
page.on('pageerror', (e) => reqs.push(`PAGEERROR ${e.message}`))
try {
  await page.goto('https://flairmedia.com.cn:38880/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(5000)
  console.log('URL:', page.url())
  console.log('TITLE:', await page.title())
  const body = await page.locator('body').innerText().catch(() => '')
  console.log('BODY:', body.slice(0, 1500))
  const inputs = await page.locator('input').evaluateAll((els) =>
    els.map((e) => ({
      type: e.getAttribute('type'),
      name: e.getAttribute('name'),
      id: e.getAttribute('id'),
      placeholder: e.getAttribute('placeholder'),
      autocomplete: e.getAttribute('autocomplete'),
    }))
  )
  console.log('INPUTS:', JSON.stringify(inputs, null, 2))
  const imgs = await page.locator('img').evaluateAll((els) =>
    els.map((e) => ({ src: e.getAttribute('src'), alt: e.getAttribute('alt'), cls: e.className })).slice(0, 30)
  )
  console.log('IMGS:', JSON.stringify(imgs, null, 2))
  const buttons = await page.locator('button, [role="button"], a').evaluateAll((els) =>
    els.map((e) => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 40)
  )
  console.log('BUTTONS/LINKS:', JSON.stringify([...new Set(buttons)], null, 2))
  const ls = await page.evaluate(() => Object.keys(localStorage))
  const ss = await page.evaluate(() => Object.keys(sessionStorage))
  console.log('localStorage keys:', JSON.stringify(ls))
  console.log('sessionStorage keys:', JSON.stringify(ss))
  await page.screenshot({ path: 'screenshots/platform-login.png', fullPage: false })
  console.log('SCREENSHOT: web/screenshots/platform-login.png')
} catch (e) {
  console.log('NAV_ERROR:', e.message)
}
console.log('NETWORK:')
console.log([...new Set(reqs)].slice(0, 80).join('\n'))
await browser.close()
