# 团队复现指南（last 分支）

> 目标：拉取后 10 分钟内跑起本地演示；第三方包请各自安装（不要提交 `.venv` / `node_modules` / 浏览器缓存）。

## 1. 前置

- Windows 10/11，PowerShell
- Python **3.14**（项目 `.venv` 实测 3.14.6）
- Node **22+**、pnpm 9+（可 `corepack enable`）
- Chrome 或 Edge（地图 / PDF 都用本机浏览器）
- Git、GitHub 仓库访问权限

## 2. 拉取与分支

```powershell
git clone https://github.com/Esmer615/ProposalStudio.git
cd ProposalStudio
git checkout last
```

## 3. Python 环境

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m ensurepip --upgrade
python -m pip install -r requirements.txt -r requirements-agent.txt
```

如果 PowerShell 禁止激活脚本，可先 `Set-ExecutionPolicy -Scope Process Bypass`，或直接用 `.\.venv\Scripts\python.exe -m pip ...`。

## 4. 前端

```powershell
pnpm --dir web install
pnpm --dir web build
```

开发模式：`pnpm --dir web dev`（4321）；生产模式由 FastAPI 直接服务 `web/dist`。

## 5. 环境变量

```powershell
Copy-Item .env.example .env
Copy-Item web/.env.example web/.env
```

- `.env`：DeepSeek Key 可选（不填自动回退确定性规则）；红豆账号用于实时刷新（可选）。
- `web/.env`：高德 Web JS API Key / 安全密钥；不填时地图保留静态兜底，其余功能可用。
- **不要提交 `.env`、OAuth 缓存、`platform_storage.json` 或任何凭证。**

## 6. 启动与演示

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8010
# 或 .\start-dev.ps1
```

- 输入页：`http://127.0.0.1:8010/input.html`
- 推荐 demo run：`c20c490c4492`（32 公交 + 6 地铁，38/38 线路 ready）
  - 概览：`http://127.0.0.1:8010/result/overview.html?run=c20c490c4492`
  - 媒体：`http://127.0.0.1:8010/result/media.html?run=c20c490c4492`
  - PDF：`http://127.0.0.1:8010/proposals/c20c490c4492.pdf`

仓库已包含 `data/snapshots`、`data/runs`、`data/external/platform/queries` 供离线演示；**不包含**红豆凭证、新云登录会话或平台 token。

## 7. 生成提案 PDF

```powershell
.\.venv\Scripts\python.exe -m server.proposal_pdf c20c490c4492
```

输出：`data/exports/proposals/<run_id>.pdf`，并复制到 `web/public/proposals` / `web/dist/proposals`。overview 概览页有「下载提案 PDF」按钮。

## 8. 测试

```powershell
.\test.ps1
# 或
.\.venv\Scripts\python.exe -m pytest engine/tests server/tests agent/tests -q
pnpm --dir web build
```

## 9. 实时数据（可选）

- 红豆：配置 `HONGDOU_USER/HONGDOU_PASS` 或 `scripts/.credentials`，运行 `.claude/skills/hongdou-inventory/scripts/snapshot.py`；无凭证时使用仓库内快照。
- 新云：执行 `node .claude/skills/xinyun-bigdata/scripts/login.mjs` 人工过一次验证码；脚本依赖未提交，先在 `.claude/skills/xinyun-bigdata/scripts` 执行 `npm install`。会话只保存在本机 `data/external/platform_storage.json`，切勿提交。
- 新云平台只有 2023-05 轨迹快照；线路几何仅用于可视化，不进入报价/库存/Reach/评分。
