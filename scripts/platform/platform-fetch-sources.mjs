import fs from 'node:fs'
import path from 'node:path'
import { request } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'sources')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })

const api = await request.newContext({
  baseURL: 'https://flairmedia.com.cn:38880',
  storageState: STATE,
  ignoreHTTPSErrors: true,
})

const paths = [
  '/nearbyPoiLineQuery',
  '/conditionQuery',
  '/looseQuery',
  '/looseMultiQuery',
  '/comparePage',
  '/queryPage',
  '/busLineShowSolution',
  '/busLineShowSolutionStation',
  '/js/common.js',
  '/js/nearbyPoiLineQuery.js',
  '/js/conditionQuery.js',
  '/js/looseQuery.js',
  '/js/looseMultiQuery.js',
  '/js/queryPage.js',
  '/js/comparePage.js',
  '/js/busLineShowSolution.js',
]
for (const p of paths) {
  try {
    const r = await api.get(p)
    const ct = r.headers()['content-type'] || ''
    const buf = await r.body()
    const name = p.replace(/^\//, '').replace(/[\/?&=]+/g, '_')
    fs.writeFileSync(path.join(OUT, name + (ct.includes('html') ? '.html' : '.js')), buf)
    console.log(r.status(), ct.split(';')[0], p, buf.length)
  } catch (e) {
    console.log('ERR', p, e.message)
  }
}
await api.dispose()
console.log('SAVED:', OUT)
