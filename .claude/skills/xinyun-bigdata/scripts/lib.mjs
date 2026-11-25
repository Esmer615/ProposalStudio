import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

// .claude/skills/xinyun-bigdata/scripts -> project root
export const ROOT = path.resolve(import.meta.dirname, '../../../..')
// Prefer the skill-local install (scripts/package.json); fall back to the
// project's web dependency for older checkouts.
let playwright
try {
  playwright = createRequire(path.join(import.meta.dirname, 'package.json'))('playwright')
} catch {
  try {
    playwright = createRequire(path.join(ROOT, 'web', 'package.json'))('@playwright/test')
  } catch {
    throw new Error('缺少 Playwright：请在 .claude/skills/xinyun-bigdata/scripts 运行 npm install playwright')
  }
}
export const { chromium, request: apiRequest } = playwright

// XINYUN_BASE / XINYUN_STATE are only for local mock-server tests; real runs use
// the platform host and the manually saved session.
export const BASE = process.env.XINYUN_BASE || 'https://flairmedia.com.cn:38880'
export const STATE = process.env.XINYUN_STATE || path.join(ROOT, 'data', 'external', 'platform_storage.json')
export const CRED = path.join(ROOT, 'scripts', '.credentials')
export const OUT = path.join(ROOT, 'data', 'external', 'platform', 'queries')

export const DATE_DEFAULT = '202305' // platform only has 2023-05 data
export const DATA_URL = '/bbf8e41e454b47126290905525c69f7'
export const INDICATORS = [
  'visitorsFlowrateAndcrowdSpeed',
  'circleCross',
  'regionAttribute',
  'crowdAge',
  'crowdGender',
  'crowdHouse',
  'crowdConsumption',
  'crowdPhoneNew',
]
export const EXPORT_INDICATORS =
  'coverPeoples,visitorsFlowrate,regionAttribute,crowdAge,crowdGender,crowdHouse,crowdIndividualConsumption,crowdPhone,crowdExtInfo'

export function loadCredentials() {
  const lines = fs.readFileSync(CRED, 'utf8').split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
  if (lines.length < 2) throw new Error('scripts/.credentials 需要两行：用户名、密码')
  return { user: lines[0], pass: lines[1] }
}

async function launchBrowser(headless) {
  // Prefer the system Chrome, then Edge, then Playwright's bundled Chromium.
  const options = [{ channel: 'chrome' }, { channel: 'msedge' }, {}]
  let lastErr
  for (const extra of options) {
    try { return await chromium.launch({ headless, ...extra }) } catch (e) { lastErr = e }
  }
  throw lastErr
}

// nginx on :38880 sometimes redirects https -> http. Playwright ≥1.5x rejects
// route.continue({url}) across protocols ("New URL must have same protocol"),
// so proxy the http hop through the context's APIRequestContext instead. That
// client speaks https correctly, shares the context cookie jar, and can be
// fulfilled back into the browser.
function _proxyHeaders(headers) {
  const out = {}
  for (const [name, value] of Object.entries(headers || {})) {
    const key = name.toLowerCase()
    if (['host', 'content-length', 'connection', 'accept-encoding', 'cookie', 'origin', 'referer'].includes(key)) continue
    out[name] = value
  }
  return out
}

function _isPlatformHttp(url) {
  try {
    const u = new URL(url)
    return u.protocol === 'http:' && u.hostname === 'flairmedia.com.cn' && u.port === '38880'
  } catch {
    return false
  }
}

function _sameOriginAsBase(url) {
  try {
    return new URL(url).origin === new URL(BASE).origin
  } catch {
    return false
  }
}

async function installProtocolProxy(context) {
  await context.route('**/*', async (route) => {
    const request = route.request()
    const url = request.url()

    // Navigation: inspect the redirect before the browser follows it. When the
    // platform answers https with Location: http://…:38880/login, rewrite the
    // header to https so the browser never hits the "HTTP to HTTPS port" 400.
    if (request.isNavigationRequest() && _sameOriginAsBase(url)) {
      try {
        const response = await route.fetch({ maxRedirects: 0 })
        const headers = { ...response.headers() }
        const location = headers.location
        if (location && _isPlatformHttp(location)) {
          headers.location = location.replace(/^http:/, 'https:')
          await route.fulfill({ status: response.status(), headers, body: '' })
          return
        }
        for (const key of ['content-encoding', 'content-length', 'transfer-encoding', 'connection']) delete headers[key]
        await route.fulfill({ status: response.status(), headers, body: await response.body() })
        return
      } catch {
        return route.abort()
      }
    }

    // Non-navigation http hop (subresource/XHR): proxy it through the context's
    // APIRequestContext, which can speak https to the same origin.
    if (!_isPlatformHttp(url)) return route.continue()
    const target = url.replace(/^http:/, 'https:')
    try {
      const response = await context.request.fetch(target, {
        method: request.method(),
        headers: _proxyHeaders(request.headers()),
        data: request.postDataBuffer() ?? undefined,
        maxRedirects: 0,
        failOnStatusCode: false,
      })
      const headers = { ...response.headers() }
      for (const key of ['content-encoding', 'content-length', 'transfer-encoding', 'connection']) delete headers[key]
      await route.fulfill({ status: response.status(), headers, body: await response.body() })
    } catch {
      await route.abort()
    }
  })
}

export async function launch({ headless = true, acceptDownloads = false, storageState } = {}) {
  const browser = await launchBrowser(headless)
  const context = await browser.newContext({
    ...(storageState ? { storageState } : {}),
    ignoreHTTPSErrors: true,
    locale: 'zh-CN',
    acceptDownloads,
    viewport: { width: 1440, height: 1000 },
  })
  // Attach to the context before creating pages so every page/popup is covered.
  await installProtocolProxy(context)
  const page = await context.newPage()
  return { browser, context, page }
}

export async function postForm(page, url, fields) {
  return await page.evaluate(async ({ url, fields }) => {
    const r = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        Accept: 'application/json, text/javascript, */*; q=0.01',
      },
      body: new URLSearchParams(fields).toString(),
    })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url, fields })
}

export async function getFirstLabels(page) {
  const r = await postForm(page, '/label/queryFirstLabel', {})
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!Array.isArray(data)) throw new Error(`/label/queryFirstLabel 返回异常（${r.status}）`)
  return data
}

export async function getSecondLabels(page, firstLabel) {
  const r = await postForm(page, '/label/querySecondLabel', { firstLabel })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!Array.isArray(data)) throw new Error(`/label/querySecondLabel 返回异常（${r.status}）`)
  return data
}

export async function getThirdLabelsFor(page, firstLabel, secondLabel = '') {
  const r = await postForm(page, '/label/queryThirdLabel', { firstLabel, secondLabel })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!Array.isArray(data)) throw new Error(`/label/queryThirdLabel 返回异常（${r.status}）`)
  return data
}

export async function getConditionOptions(page) {
  const r = await postForm(page, '/conditionQuery/queryAllCondition', {})
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data || !Array.isArray(data.data)) throw new Error(`/conditionQuery/queryAllCondition 返回异常（${r.status}）`)
  return data.data
}

export async function getPoiTypes(page) {
  const r = await page.evaluate(async () => {
    const resp = await fetch('/basekeyword/query?page=0&rows=0', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    })
    return { status: resp.status, text: await resp.text() }
  })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  const rows = data?.rows || []
  return rows.map((x) => ({ id: x.id, keyName: x.keyName, keyValue: x.keyValue, keyScope: x.keyScope }))
}

export async function getSelectOptions(page, selector) {
  return await page.locator(selector).evaluate((e) => ({
    id: e.id,
    options: Array.from(e.options || []).map((o) => ({ value: o.value, text: o.text, selected: o.selected })),
  }))
}

export async function getThirdLabels(page, firstLabel) {
  const r = await postForm(page, '/label/queryThirdLabel', {
    firstLabel,
    secondLabel: '',
  })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!Array.isArray(data)) {
    throw new Error(`/label/queryThirdLabel 返回异常（${r.status}）：${r.text.slice(0, 200)}`)
  }
  return data
}

const norm = (s) => String(s ?? '').replace(/路$/g, '').replace(/\s+/g, '').trim()

export function matchLabels(allLabels, tags) {
  const found = []
  const missing = []
  for (const tag of tags) {
    const t = String(tag).trim()
    if (!t) continue
    const nt = norm(t)
    // Tiered exact-first matching so "71路" never falsely matches "1671路"
    const hit =
      allLabels.find((x) => String(x.thirdLabel).trim() === t) ||
      allLabels.find((x) => norm(x.thirdLabel) === nt) ||
      allLabels.find((x) => norm(x.ext1) === nt) ||
      allLabels.find((x) => String(x.thirdLabel).startsWith(t) && !/^\d/.test(String(x.thirdLabel).slice(t.length))) ||
      allLabels.find((x) => !/^\d+$/.test(nt) && String(x.thirdLabel).includes(t))
    if (hit) found.push({ requested: t, label: hit })
    else missing.push(t)
  }
  // de-dupe by id while keeping requested tag mapping
  const byId = new Map()
  for (const item of found) {
    const key = String(item.label.id)
    if (!byId.has(key)) {
      byId.set(key, { ...item.label, _requested: item.requested })
    }
  }
  return { labels: [...byId.values()], missing }
}

export function describeLabel(x) {
  return {
    id: x.id,
    firstLabel: x.firstLabel,
    secondLabel: x.secondLabel,
    thirdLabel: x.thirdLabel,
    ext1: x.ext1,
    ext4: x.ext4,
  }
}

export async function fetchIndicators(page, labelIds, dateMonth) {
  const extOptions = JSON.stringify({ gridType: '500', underground: '0' })
  const result = {}
  for (const indicatorType of INDICATORS) {
    const r = await postForm(page, DATA_URL, {
      queryType: '1',
      indicatorType,
      dataMonth: dateMonth,
      labelIds: labelIds.join(','),
      gridIds: '',
      extOptions,
    })
    let parsed = null
    try { parsed = JSON.parse(r.text) } catch {}
    result[indicatorType] = {
      status: r.status,
      code: parsed?.code ?? null,
      data: parsed?.data ?? null,
      rawText: parsed ? undefined : r.text.slice(0, 2000),
    }
  }
  return result
}

export function buildSummary(indicators) {
  const age = indicators.crowdAge?.data?.[0] || {}
  const gender = indicators.crowdGender?.data?.[0] || {}
  const house = indicators.crowdHouse?.data?.[0] || {}
  const consumption = indicators.crowdConsumption?.data?.[0] || {}
  const regionAttr = Array.isArray(indicators.regionAttribute?.data) ? indicators.regionAttribute.data : []
  const phones = Array.isArray(indicators.crowdPhoneNew?.data) ? indicators.crowdPhoneNew.data : []
  const flow = Array.isArray(indicators.visitorsFlowrateAndcrowdSpeed?.data)
    ? indicators.visitorsFlowrateAndcrowdSpeed.data
    : []
  const topPhones = [...phones].sort((a, b) => (b.num || 0) - (a.num || 0)).slice(0, 8)
  const flowValues = flow.flatMap((x) => [x.time1, x.time2, x.time3, x.time4]).filter((v) => typeof v === 'number')
  const byType = (t) => flow.find((x) => x && x.type === t) || null
  const vf = byType('visitorsFlowrate')
  const pvRow = byType('coverPeoplesPV')
  const uvRow = byType('coverPeoplesUV')
  const pvAccRow = byType('coverPeoplesPVAccurate')
  const flowPeriods = vf
    ? {
        morning: Number(vf.time1 || 0),
        midday: Number(vf.time2 || 0),
        evening: Number(vf.time3 || 0),
        night: Number(vf.time4 || 0),
      }
    : null
  const pct = (v) => (typeof v === 'number' ? Math.round(v * 10000) / 100 : null)
  return {
    under20_pct: age.age1 ?? null,
    age_20_30_pct: age.age2 ?? null,
    age_30_40_pct: age.age3 ?? null,
    age_40_50_pct: age.age4 ?? null,
    age_50plus_pct: age.age5 ?? null,
    male_pct: gender.male ?? null,
    female_pct: gender.female ?? null,
    house: house,
    house_pct: {
      zero: pct(house.zero),
      one: pct(house.one),
      two: pct(house.two),
      more: pct(house.more),
    },
    consumption: Object.keys(consumption).length
      ? {
          low: Math.round(((Number(consumption.ilow1 || 0) + Number(consumption.ilow2 || 0) + Number(consumption.ilow3 || 0)) * 100)) / 100,
          ilow1: consumption.ilow1 ?? null,
          ilow2: consumption.ilow2 ?? null,
          ilow3: consumption.ilow3 ?? null,
          middle: consumption.imiddle ?? null,
          high: consumption.ihigh ?? null,
          family_low: consumption.flow ?? null,
          family_middle: consumption.fmiddle ?? null,
          family_high: consumption.fhigh ?? null,
        }
      : null,
    region_attribute: regionAttr,
    top_phones: topPhones,
    flow_periods: flowPeriods,
    cover_pv: pvRow ? Number(pvRow.time1 || 0) : null,
    cover_uv: uvRow ? Number(uvRow.time1 || 0) : null,
    cover_pv_accurate: pvAccRow ? Number(pvAccRow.time1 || 0) : null,
    flow_points: flow.length,
    flow_nonzero_points: flowValues.filter((v) => v !== 0).length,
    flow_max: flowValues.length ? Math.max(...flowValues) : null,
  }
}

// --------------------------------------------------------------------------- //
// Shared helpers for the submodules
// --------------------------------------------------------------------------- //
export async function geocode(page, address, city = '上海市') {
  const r = await page.evaluate(async ({ address, city }) => {
    const resp = await fetch('/nearby/geocode', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ address, city }),
    })
    return { status: resp.status, text: await resp.text() }
  }, { address, city })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data?.data) throw new Error(`地理编码失败（${r.status}）：${r.text.slice(0, 200)}`)
  return {
    ...data.data,
    lng: Number(data.data.lng),
    lat: Number(data.data.lat),
    address,
  }
}

export function circleBorder(lng, lat, radiusM, points = 36) {
  const pts = []
  const latRad = (lat * Math.PI) / 180
  for (let i = 0; i <= points; i++) {
    const a = (i / points) * Math.PI * 2
    const dLat = (radiusM / 111320) * Math.cos(a)
    const dLng = (radiusM / (111320 * Math.cos(latRad))) * Math.sin(a)
    pts.push(`${(lng + dLng).toFixed(7)} ${(lat + dLat).toFixed(7)}`)
  }
  return pts.join(',')
}

export async function queryLabelByBorder(page, border, dateMonth, isHD = '0') {
  const r = await postForm(page, '/label/queryLabelByBorder', {
    numStr: '0',
    border,
    dataMonth: dateMonth,
    isHD,
  })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`地址查询失败（${r.status}）：${r.text.slice(0, 300)}`)
  return data
}

export async function queryCondition(page, condition, dateMonth) {
  const r = await postForm(page, '/label/queryLabelByQueryCondition', {
    queryCondition: condition,
    dataMonth: dateMonth,
  })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`条件查询失败（${r.status}）：${r.text.slice(0, 300)}`)
  return data
}

export async function matchCover(page, center, radius, mediaTypes = ['bus', 'metro'], lineScope = 'all') {
  const r = await page.evaluate(async ({ center, radius, mediaTypes, lineScope }) => {
    const resp = await fetch('/baseInfoLine/matchCoverLines', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({
        radius,
        mediaTypes,
        lineScope,
        centers: [center],
      }),
    })
    return { status: resp.status, text: await resp.text() }
  }, { center, radius, mediaTypes, lineScope })
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`覆盖查询失败（${r.status}）：${r.text.slice(0, 300)}`)
  return data
}

export async function getLineTree(page, type = 'line') {
  const url = type === 'station' ? '/baseInfoLine/getTreeLine?type=station' : '/baseInfoLine/getTreeLine'
  const r = await page.evaluate(async (url) => {
    const resp = await fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    })
    return { status: resp.status, text: await resp.text() }
  }, url)
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`AI线路树读取失败（${r.status}）：${r.text.slice(0, 300)}`)
  return data.data ?? data
}

export function flattenTree(nodes) {
  const out = []
  const walk = (arr) => {
    for (const n of arr || []) {
      out.push(n)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

export async function getLineJson(page, linePath) {
  const r = await page.evaluate(async (linePath) => {
    const resp = await fetch('/baseInfoLine/getLineJson?linePath=' + encodeURIComponent(linePath), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    })
    return { status: resp.status, text: await resp.text() }
  }, linePath)
  let data = null
  try { data = JSON.parse(r.text) } catch {}
  if (!data) throw new Error(`线路几何读取失败（${r.status}）：${r.text.slice(0, 300)}`)
  let inner = data.data
  if (typeof inner === 'string') {
    try { inner = JSON.parse(inner) } catch {}
  }
  return inner
}

// Shared export flow for both query modes: POST /exportIndicatorData from the
// /infoPage context, then GET /downloadExcel and save the .xls locally.
async function exportIndicators(context, params, outDir, safeName) {
  // The export endpoint only works in the /infoPage context.
  const page = await context.newPage()
  try {
    await page.goto(BASE + '/infoPage', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(2000)
    const r = await postForm(page, '/exportIndicatorData', { ...params, fileName: safeName })
    let data = null
    try { data = JSON.parse(r.text) } catch {}
    if (data?.code !== '0000' || !data?.data) {
      throw new Error(`导出失败（${r.status}）：${r.text.slice(0, 300)}`)
    }
    const filePath = encodeURI(encodeURI(String(data.data)))
    const fn = encodeURI(encodeURI(`${safeName}.xls`))
    const url = `${BASE}/downloadExcel?filePath=${filePath}&excelType=1&fileName=${fn}`
    const dl = await context.request.get(url)
    const buf = await dl.body()
    fs.mkdirSync(outDir, { recursive: true })
    const out = path.join(outDir, `${safeName}.xls`)
    fs.writeFileSync(out, buf)
    return { path: out, bytes: buf.length, status: dl.status(), ct: dl.headers()['content-type'] }
  } finally {
    await page.close()
  }
}

// 组合查询与条件查询共用：queryType=1 + labelIds
export async function exportExcel(context, labelIds, dateMonth, outDir, fileName) {
  const safeName = fileName || `大数据洞察_${labelIds.join('_')}_${dateMonth}`
  return exportIndicators(context, {
    queryType: '1',
    indicatorType: EXPORT_INDICATORS,
    dataMonth: dateMonth,
    labelIds: labelIds.join(','),
    gridIds: '',
    extOptions: JSON.stringify({ gridType: '500', underground: '0' }),
  }, outDir, safeName)
}
