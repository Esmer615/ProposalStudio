import fs from 'node:fs'
import path from 'node:path'
import { BASE, STATE, OUT, launch, getLineTree, flattenTree } from './lib.mjs'

// AI线路：保存方案 → 授权外部访问 → 生成可分享的百度地图 HTML 链接 + 导出线路明细。
// Example:
//   node ai_share.mjs --line 1001 --remark "skill share test"
// 说明：这是写操作（会在平台历史记录创建一条方案并授权一个月），仅在用户明确要求分享时执行。

function arg(name, def = undefined) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : def
}
const lineArg = arg('--line')
const remark = arg('--remark', 'Skill 生成：AI线路可视化分享')
const nameArg = arg('--name')
const outDir = path.resolve(arg('--out', OUT))
fs.mkdirSync(outDir, { recursive: true })

if (!fs.existsSync(STATE)) {
  console.error('缺少登录会话。先运行: node .claude/skills/xinyun-bigdata/scripts/login.mjs')
  process.exit(2)
}
if (!lineArg) {
  console.error('用法: node ai_share.mjs --line 1001 --remark "..."')
  process.exit(2)
}

async function postJson(page, url, body) {
  return await page.evaluate(async ({ url, body }) => {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: JSON.stringify(body) })
    return { status: r.status, text: await r.text() }
  }, { url, body })
}
async function postForm(page, url, fields) {
  return await page.evaluate(async ({ url, fields }) => {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, body: new URLSearchParams(fields).toString() })
    return { status: r.status, text: await r.text() }
  }, { url, fields })
}

const { browser, context, page } = await launch({ headless: true, storageState: STATE })
try {
  await page.goto(BASE + '/busLineShowSolution', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(1500)
  const tree = await getLineTree(page, 'line')
  const flat = flattenTree(tree)
  const norm = (s) => String(s ?? '').replace(/路$/g, '').trim()
  const node = flat.find((n) => n.lineName && (norm(n.lineName) === norm(lineArg) || String(n.lineName).includes(norm(lineArg))))
  if (!node) {
    console.error(`未找到线路 ${lineArg}`)
    process.exit(3)
  }
  const name = nameArg || `skill_${node.lineName}_${new Date().toISOString().slice(0, 10)}`
  const savePayload = {
    name,
    remark,
    state: 1,
    lineList: [node],
    csvList: [],
    areaList: [],
  }
  const saved = await postJson(page, '/baseInfoWeb/saveWeb', savePayload)
  console.log('SAVE', saved.status, saved.text.slice(0, 800))
  let savedData = null
  try { savedData = JSON.parse(saved.text) } catch {}

  // Find webId: response may carry data.id; otherwise query history list.
  let webId = savedData?.data?.id ?? savedData?.data ?? savedData?.id ?? null
  if (webId && typeof webId === 'object') webId = webId.id ?? null
  if (!webId) {
    const hist = await postForm(page, '/baseInfoWeb/getWeb', { pageNum: '1', pageSize: '20' })
    let hd = null
    try { hd = JSON.parse(hist.text) } catch {}
    const rows = hd?.data || hd?.rows || []
    const hit = rows.find((r) => r.showName === name || String(r.name || '').includes(name))
    if (hit) webId = hit.id
    console.log('HISTORY', hist.status, 'rows', rows.length, 'match', hit ? hit.id : 'none')
  }
  if (!webId) {
    console.error('无法确定 webId；请查看 /historyLineList 或平台返回。')
    process.exit(4)
  }
  console.log('WEB_ID:', webId)

  const auth = await postJson(page, '/baseInfoAuth/save', { webId, remark })
  console.log('AUTH', auth.status, auth.text.slice(0, 500))

  const shareUrl = `${BASE}/busLineShow?webId=${encodeURIComponent(webId)}`
  console.log('SHARE_URL:', shareUrl)

  const detail = await context.request.get(`${BASE}/baseInfoWeb/exportWebLineDetail?webId=${encodeURIComponent(webId)}`)
  const buf = await detail.body()
  const exportFile = path.join(outDir, `ai_line_detail_${webId}.xls`)
  fs.writeFileSync(exportFile, buf)
  console.log('EXPORT:', exportFile, buf.length, 'bytes', detail.headers()['content-type'])

  const payload = {
    meta: { source: '新云传媒大数据可视化平台', platform: BASE, savedAt: new Date().toISOString(), note: '保存+授权外部访问（默认一个月）；分享链接为平台官方百度地图 HTML。' },
    line: { lineId: node.lineId, lineName: node.lineName, linePath: node.linePath },
    name, remark, webId, shareUrl, exportFile,
  }
  const file = path.join(outDir, `ai_share_${webId}.json`)
  fs.writeFileSync(file, JSON.stringify(payload, null, 2), 'utf8')
  console.log('JSON:', file)
} catch (e) {
  console.error('AI_SHARE_ERROR:', e.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
