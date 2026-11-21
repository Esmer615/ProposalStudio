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

async function get(url) {
  return await page.evaluate(async (url) => {
    const r = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json, text/javascript, */*; q=0.01', 'X-Requested-With': 'XMLHttpRequest' } })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, url)
}
async function postJson(url, body) {
  return await page.evaluate(async ({ url, body }) => {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url, body })
}
async function postForm(url, fields) {
  return await page.evaluate(async ({ url, fields }) => {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: new URLSearchParams(fields).toString() })
    return { status: r.status, ct: r.headers.get('content-type'), text: await r.text() }
  }, { url, fields })
}

try {
  await page.goto('https://flairmedia.com.cn:38880/busLineShowSolution', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(3000)
  const tree = await get('/baseInfoLine/getTreeLine')
  let td = null
  try { td = JSON.parse(tree.text) } catch {}
  const nodes = td?.data || td
  console.log('TREE status', tree.status, 'bytes', tree.text.length, 'topKeys', td ? Object.keys(td) : null, 'nodes', Array.isArray(nodes) ? nodes.length : typeof nodes)
  console.log('TREE sample', JSON.stringify(Array.isArray(nodes) ? nodes.slice(0, 2) : nodes, null, 1).slice(0, 3000))
  let lineNode = null
  function walk(arr) {
    for (const n of arr || []) {
      if (String(n.lineName) === '1001' || String(n.lineId) === '1001' || String(n.lineName) === '1001路') { lineNode = n; return }
      if (n.children) walk(n.children)
    }
  }
  if (Array.isArray(nodes)) walk(nodes)
  console.log('LINE 1001 NODE:', JSON.stringify(lineNode, null, 1))
  if (lineNode) {
    const lp = lineNode.linePath || lineNode.path || lineNode.lineName
    const geo = await get('/baseInfoLine/getLineJson?linePath=' + encodeURIComponent(lp))
    console.log('GEO status', geo.status, 'bytes', geo.text.length)
    console.log('GEO preview', geo.text.slice(0, 1500))
  }

  // Address query
  const geoAddr = await postJson('/nearby/geocode', { address: '上海乐高乐园', city: '上海市' })
  console.log('GEOCODE', geoAddr.status, geoAddr.text.slice(0, 500))
  let gd = null
  try { gd = JSON.parse(geoAddr.text) } catch {}
  const center = gd?.data
  if (center) {
    const lng = Number(center.lng), lat = Number(center.lat)
    const radius = 1000
    const pts = []
    for (let i = 0; i <= 36; i++) {
      const a = (i / 36) * Math.PI * 2
      const dLat = (radius / 111320) * Math.cos(a)
      const dLng = (radius / (111320 * Math.cos(lat * Math.PI / 180))) * Math.sin(a)
      pts.push(`${(lng + dLng).toFixed(7)} ${(lat + dLat).toFixed(7)}`)
    }
    const border = pts.join(',')
    const q = await postForm('/label/queryLabelByBorder', { numStr: '0', border, dataMonth: '202305', isHD: '0' })
    console.log('BORDER status', q.status, 'bytes', q.text.length)
    console.log('BORDER preview', q.text.slice(0, 2000))
    let qd = null
    try { qd = JSON.parse(q.text) } catch {}
    console.log('BORDER keys', qd ? Object.keys(qd) : null, 'labels', Array.isArray(qd?.labels) ? qd.labels.length : qd?.[0]?.labels?.length, 'sopExtendData', Array.isArray(qd?.sopExtendData) ? qd.sopExtendData.length : null)
  }
} catch (e) {
  console.log('MODULE_PROBE_ERROR:', e.message)
}
await browser.close()
