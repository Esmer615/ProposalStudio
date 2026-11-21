import fs from 'node:fs'
import path from 'node:path'
import { request } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'sources')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
const api = await request.newContext({ baseURL: 'https://flairmedia.com.cn:38880', storageState: STATE, ignoreHTTPSErrors: true })
for (const p of ['/js/showLine/busLineShow.js', '/js/showLine/busLineShowStation.js']) {
  const r = await api.get(p)
  const b = await r.body()
  const name = p.replace(/^\//, '').replace(/[\/?&=]+/g, '_')
  fs.writeFileSync(path.join(OUT, name), b)
  console.log(r.status(), p, b.length)
}
await api.dispose()
