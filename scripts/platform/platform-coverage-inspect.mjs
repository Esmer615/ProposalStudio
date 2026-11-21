import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external')
const STATE = path.join(OUT, 'platform_storage.json')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})

try {
  await page.goto('https://flairmedia.com.cn:38880/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(5000)
  console.log('URL:', page.url())
  console.log('TITLE:', await page.title())

  // Scripts
  const scripts = await page.locator('script[src]').evaluateAll((els) => els.map((e) => e.getAttribute('src')))
  console.log('SCRIPTS:', JSON.stringify(scripts, null, 2))

  // Fetch same-origin scripts with the session and grep endpoint-looking lines
  const snippets = []
  for (const src of scripts) {
    if (!src || !src.startsWith('/')) continue
    if (!/near|cover|poi|line|query|index|common|map/i.test(src)) continue
    try {
      const r = await context.request.get('https://flairmedia.com.cn:38880' + src)
      if (!r.ok()) continue
      const t = await r.text()
      const lines = t.split(/\r?\n/).filter((l) => /url\s*:|ajax|export|cover|nearby|query|analysis|download|excel/i.test(l))
      snippets.push({ src, bytes: t.length, sample: lines.slice(0, 80) })
    } catch (e) {
      snippets.push({ src, error: e.message })
    }
  }
  console.log('SCRIPT_SNIPPETS:', JSON.stringify(snippets, null, 2).slice(0, 30000))

  // Inline scripts
  const inline = await page.locator('script:not([src])').evaluateAll((els) => els.map((e) => e.textContent || ''))
  const inlineHits = inline
    .flatMap((t) => t.split(/\r?\n/))
    .filter((l) => /url\s*:|ajax|export|cover|nearby|query|analysis|download|excel/i.test(l))
  console.log('INLINE_HITS:', JSON.stringify(inlineHits.slice(0, 200), null, 2))

  // Form controls with labels / nearby text
  const controls = await page.locator('input, select, textarea, button, a').evaluateAll((els) =>
    els
      .map((e) => {
        const text = (e.innerText || '').trim()
        const label = e.closest('td,div,span')?.innerText?.slice(0, 80) || ''
        return {
          tag: e.tagName,
          type: e.getAttribute('type'),
          id: e.id,
          name: e.getAttribute('name'),
          value: e.getAttribute('value'),
          placeholder: e.getAttribute('placeholder'),
          text: text.slice(0, 60),
          label: label.replace(/\s+/g, ' ').slice(0, 100),
          onclick: e.getAttribute('onclick'),
          visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
        }
      })
      .filter((x) => x.id || x.name || x.text || x.onclick)
  )
  console.log('CONTROLS:', JSON.stringify(controls.slice(0, 160), null, 2))
  await page.screenshot({ path: 'screenshots/platform-coverage-page.png', fullPage: false })
  console.log('SCREENSHOT: web/screenshots/platform-coverage-page.png')
} catch (e) {
  console.log('INSPECT_ERROR:', e.message)
}
await browser.close()
