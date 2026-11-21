import fs from 'node:fs'
import path from 'node:path'
import { request } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'sources')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
const api = await request.newContext({ baseURL: 'https://flairmedia.com.cn:38880', storageState: STATE, ignoreHTTPSErrors: true })
const r = await api.get('/historyLineList')
const html = await r.text()
fs.writeFileSync(path.join(OUT, 'historyLineList.html'), html, 'utf8')
console.log('historyLineList', r.status(), html.length)
const scripts = [...html.matchAll(/<script[^>]+src=["']([^"']+)["']/gi)].map((m) => m[1])
console.log('scripts', scripts)
for (const src of scripts) {
  if (!src.startsWith('/')) continue
  try {
    const rr = await api.get(src)
    const b = await rr.body()
    const name = 'hist_' + src.split('/').pop()
    fs.writeFileSync(path.join(OUT, name), b)
    console.log(rr.status(), src, b.length)
  } catch (e) { console.log('ERR', src, e.message) }
}
await api.dispose()
