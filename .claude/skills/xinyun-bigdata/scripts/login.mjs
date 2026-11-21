import fs from 'node:fs'
import path from 'node:path'
import { ROOT, STATE, BASE, loadCredentials, launch } from './lib.mjs'

// Manual captcha login. Opens a visible Chrome, pre-fills account/password,
// focuses the captcha input, waits for the user to log in, then saves the
// session to data/external/platform_storage.json (local, gitignored).
// Never prints credentials.

fs.mkdirSync(path.dirname(STATE), { recursive: true })
const cred = loadCredentials()
console.log('credentials loaded (values hidden)')
console.log('打开浏览器后请输入验证码并点击“登录”（最多等待 5 分钟）...')

const { browser, context, page } = await launch({ headless: false })
try {
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  await page.locator('input[placeholder="请输入用户名/手机号"]').first().fill(cred.user)
  await page.locator('input[placeholder="请输入密码"]').first().fill(cred.pass)
  await page.locator('input[placeholder="验证码"]').first().focus()

  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 300000 })
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {})
  await page.waitForTimeout(1500)
  await context.storageState({ path: STATE })
  console.log('LOGIN_OK:', page.url())
  console.log('SESSION_SAVED:', STATE)
} catch (e) {
  console.log('LOGIN_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
