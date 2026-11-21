import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'platform')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const CENTERS = [
  { slug: 'lego', name: '上海乐高乐园', address: '上海市金山区枫泾镇', lng: 121.104, lat: 30.88 },
  { slug: 'disney', name: '上海迪士尼度假区', address: '上海市浦东新区川沙新镇', lng: 121.657, lat: 31.144 },
  { slug: 'haichang', name: '上海海昌海洋公园', address: '上海市浦东新区临港新城', lng: 121.903, lat: 30.894 },
  { slug: 'peoples_square', name: '人民广场', address: '上海市黄浦区人民广场', lng: 121.475, lat: 31.232 },
  { slug: 'lujiazui', name: '陆家嘴', address: '上海市浦东新区陆家嘴', lng: 121.506, lat: 31.239 },
  { slug: 'xujiahui', name: '徐家汇', address: '上海市徐汇区徐家汇', lng: 121.437, lat: 31.195 },
  { slug: 'jingan', name: '静安寺', address: '上海市静安区静安寺', lng: 121.445, lat: 31.223 },
  { slug: 'hongqiao', name: '虹桥火车站', address: '上海市闵行区虹桥火车站', lng: 121.327, lat: 31.2 },
  { slug: 'shanghai_south', name: '上海南站', address: '上海市徐汇区上海南站', lng: 121.429, lat: 31.154 },
  { slug: 'wujiaochang', name: '五角场', address: '上海市杨浦区五角场', lng: 121.514, lat: 31.303 },
  { slug: 'qibao', name: '七宝', address: '上海市闵行区七宝', lng: 121.349, lat: 31.155 },
  { slug: 'zhongshan_park', name: '中山公园', address: '上海市长宁区中山公园', lng: 121.419, lat: 31.22 },
]
const RADII = [500, 1000, 3000, 5000]

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
for (const c of CENTERS) {
  for (const radius of RADII) {
    const payload = {
      radius,
      mediaTypes: ['bus', 'metro'],
      lineScope: 'all',
      centers: [{ name: c.name, address: c.address, lng: c.lng, lat: c.lat }],
    }
    try {
      const result = await page.evaluate(async ({ url, body }) => {
        const r = await fetch(url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
          body: JSON.stringify(body),
        })
        return { status: r.status, text: await r.text() }
      }, { url: '/baseInfoLine/matchCoverLines', body: payload })
      const file = path.join(OUT, `coverage_${c.slug}_${radius}.json`)
      fs.writeFileSync(file, result.text, 'utf8')
      let data = null
      try { data = JSON.parse(result.text) } catch {}
      const items = data?.data || []
      const metro = items.filter((x) => x.mediaType === 'metro')
      const bus = items.filter((x) => x.mediaType === 'bus')
      console.log(`${c.slug} r=${radius}: status=${result.status} items=${items.length} bus=${bus.length} metro=${metro.length}`)
      if (metro.length) console.log('  metro sample:', JSON.stringify(metro[0]))
      manifest.push({ center: c, radius, status: result.status, bytes: result.text.length, items: items.length, bus: bus.length, metro: metro.length, file: path.relative(ROOT, file), fetchedAt: new Date().toISOString() })
    } catch (e) {
      console.log(`${c.slug} r=${radius}: ERROR ${e.message}`)
      manifest.push({ center: c, radius, error: e.message })
    }
  }
}
fs.writeFileSync(path.join(OUT, 'coverage_manifest.json'), JSON.stringify(manifest, null, 2), 'utf8')
console.log('MANIFEST:', path.join(OUT, 'coverage_manifest.json'))
await browser.close()
