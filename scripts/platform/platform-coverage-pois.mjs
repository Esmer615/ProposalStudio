import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
const POI = path.join(ROOT, 'data', 'geo', 'poi_theme_park.geojson')
fs.mkdirSync(OUT, { recursive: true })

const geo = JSON.parse(fs.readFileSync(POI, 'utf8'))
const centers = []
const seen = new Set()
for (const f of geo.features || []) {
  const p = f.properties || {}
  const c = f.geometry?.coordinates || []
  if (c.length < 2) continue
  const name = p.name || p.id || `poi_${centers.length}`
  const key = `${name}|${c[0].toFixed(4)}|${c[1].toFixed(4)}`
  if (seen.has(key)) continue
  seen.add(key)
  centers.push({ id: p.id || `poi_${centers.length}`, name, type: p.type || 'poi', lng: Number(c[0]), lat: Number(c[1]) })
}
console.log('POI centers:', centers.length)
const RADII = [1000, 3000]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: STATE, ignoreHTTPSErrors: true, locale: 'zh-CN' })
const page = await context.newPage()
await page.route('**/*', (route) => {
  const u = route.request().url()
  if (u.startsWith('http://flairmedia.com.cn:38880')) return route.continue({ url: u.replace('http://', 'https://') })
  return route.continue()
})
await page.goto('https://flairmedia.com.cn:38880/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForTimeout(2000)

const manifest = []
let idx = 0
for (const c of centers) {
  for (const radius of RADII) {
    const payload = {
      radius,
      mediaTypes: ['bus', 'metro'],
      lineScope: 'all',
      centers: [{ name: c.name, address: c.name, lng: c.lng, lat: c.lat }],
    }
    try {
      const r = await page.evaluate(async ({ url, body }) => {
        const resp = await fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
          body: JSON.stringify(body),
        })
        return { status: resp.status, text: await resp.text() }
      }, { url: '/baseInfoLine/matchCoverLines', body: payload })
      const safe = String(c.id).replace(/[^\w-]+/g, '_')
      const file = path.join(OUT, `coverage_poi_${safe}_${radius}.json`)
      fs.writeFileSync(file, r.text, 'utf8')
      let data = null
      try { data = JSON.parse(r.text) } catch {}
      const items = data?.data || []
      manifest.push({
        center: c,
        radius,
        status: r.status,
        bytes: r.text.length,
        items: items.length,
        bus: items.filter((x) => x.mediaType === 'bus').length,
        metro: items.filter((x) => x.mediaType === 'metro').length,
        file: path.relative(ROOT, file),
        fetchedAt: new Date().toISOString(),
      })
    } catch (e) {
      manifest.push({ center: c, radius, error: e.message })
    }
    idx++
    if (idx % 20 === 0) console.log('progress', idx, '/', centers.length * RADII.length)
    await page.waitForTimeout(180)
  }
}
fs.writeFileSync(path.join(OUT, 'coverage_poi_manifest.json'), JSON.stringify(manifest, null, 2), 'utf8')
console.log('DONE manifest:', path.join(OUT, 'coverage_poi_manifest.json'))
await browser.close()
