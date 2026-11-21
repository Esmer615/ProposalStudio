import fs from 'node:fs'
import path from 'node:path'
import { request } from '@playwright/test'

const ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUT = path.join(ROOT, 'data', 'external', 'sources', 'info')
const STATE = path.join(ROOT, 'data', 'external', 'platform_storage.json')
fs.mkdirSync(OUT, { recursive: true })
const api = await request.newContext({ baseURL: 'https://flairmedia.com.cn:38880', storageState: STATE, ignoreHTTPSErrors: true })
const files = [
  '/js/busi/infoPage.js',
  '/js/busi/info/visitorsFlowrateAndcrowdSpeed.js',
  '/js/busi/info/crowdAttribute.js',
  '/js/busi/info/circleCross.js',
  '/js/busi/info/regionAttribute.js',
  '/js/busi/info/crowdAge.js',
  '/js/busi/info/crowdGender.js',
  '/js/busi/info/crowdMarital.js',
  '/js/busi/info/crowdLocation.js',
  '/js/busi/info/crowdCar.js',
  '/js/busi/info/crowdHouse.js',
  '/js/busi/info/crowdConsumption.js',
  '/js/busi/info/crowdPhoneNew.js',
  '/js/busi/info/crowdPhoneLevel.js',
]
for (const p of files) {
  try {
    const r = await api.get(p)
    const b = await r.body()
    const name = p.split('/').pop()
    fs.writeFileSync(path.join(OUT, name), b)
    console.log(r.status(), p, b.length)
  } catch (e) {
    console.log('ERR', p, e.message)
  }
}
await api.dispose()
