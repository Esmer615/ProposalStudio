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
const files = [
  '/js/busi/nearbyPoiLineQuery.js',
  '/js/busi/conditionQuery.js',
  '/js/busi/looseMultiQuery.js',
  '/js/busi/looseQuery.js',
  '/js/busi/queryPage.js',
  '/js/busi/busLineShowSolution.js',
  '/js/busi/busLineShowSolutionStation.js',
]
for (const p of files) {
  try {
    const r = await api.get(p)
    const body = await r.body()
    const name = p.replace(/^\//, '').replace(/[\/?&=]+/g, '_')
    fs.writeFileSync(path.join(OUT, name), body)
    console.log(r.status(), p, body.length)
  } catch (e) {
    console.log('ERR', p, e.message)
  }
}
await api.dispose()
