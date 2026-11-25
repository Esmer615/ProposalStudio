import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, launch, geocode } from './lib.mjs'

// 地理编码: address -> { name, address, lng, lat, city, source }
// Example:
//   node geocode.mjs --address "上海陆家嘴中国平安" --json

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def
}
const address = arg('--address')
const city = arg('--city', '上海市')
const jsonMode = process.argv.includes('--json')
const force = process.argv.includes('--force')
const outDir = path.resolve(arg('--out', OUT))
const cacheFile = path.join(outDir, 'geocode_cache.json')

if (!address) {
  console.error('用法: node geocode.mjs --address "静安寺" [--city 上海市] [--json]')
  process.exit(2)
}

function readCache() {
  try {
    return JSON.parse(fs.readFileSync(cacheFile, 'utf8'))
  } catch {
    return {}
  }
}

function writeCache(cache) {
  fs.mkdirSync(outDir, { recursive: true })
  const tmp = cacheFile + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(cache, null, 2), 'utf8')
  fs.renameSync(tmp, cacheFile)
}

const cacheKey = `${city}:${address.trim()}`
const cache = readCache()
if (!force && cache[cacheKey] && Number.isFinite(cache[cacheKey].lng) && Number.isFinite(cache[cacheKey].lat)) {
  const hit = { ...cache[cacheKey], cached: true }
  if (jsonMode) console.log(JSON.stringify(hit))
  else console.log('地理编码(缓存):', hit.address, '->', hit.lng, hit.lat)
  process.exit(0)
}

if (!fs.existsSync(STATE)) {
  const err = { ok: false, error: 'MANUAL_LOGIN_REQUIRED', message: '缺少登录会话' }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}

const { browser, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/nearbyPoiLineQuery', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1200)
  const g = await geocode(page, address.trim(), city)
  const out = {
    ok: true,
    name: g.name || address.trim(),
    address: g.formattedAddress || g.address || address.trim(),
    district: g.district || g.region || g.area || '',
    lng: Number(g.lng),
    lat: Number(g.lat),
    city,
    source: '新云传媒大数据可视化平台 · /nearby/geocode',
    fetchedAt: new Date().toISOString(),
    cached: false,
  }
  cache[cacheKey] = out
  writeCache(cache)
  if (jsonMode) console.log(JSON.stringify(out))
  else console.log('地理编码:', out.address, '->', out.lng, out.lat)
} catch (e) {
  const err = { ok: false, error: 'GEOCODE_ERROR', message: e.message }
  if (jsonMode) console.log(JSON.stringify(err))
  else console.error('GEOCODE_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
