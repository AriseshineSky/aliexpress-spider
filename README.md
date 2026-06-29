# AliExpress Spider

Playwright-based crawler for [AliExpress US](https://www.aliexpress.us/). Collects category listings, fetches product detail pages, parses variants/specifications/description, validates against [`StandardProduct`](https://github.com/AriseshineSky/product-validator), and exports JSONL and/or Elasticsearch.

## Features

- Category listing crawl with pagination
- Product detail parsing (API + DOM): title, price, variants, specifications, description HTML
- `StandardProduct` validation via `product-validator`
- Optional Elasticsearch upsert (`ELASTICSEARCH_URL` + `ELASTICSEARCH_INDEX` in `.env`)
- Headless-first with `--exit-on-block` (stop immediately on captcha)
- Persistent browser profile for manual verification

## Requirements

- Python **3.10+**
- Network access to GitHub (for `product-validator` zip download; **Git client not required**)
- Chromium (installed automatically via Playwright)

## Quick install

### Linux / macOS

```bash
cd /path/to/crawlers/aliexpress-spider
chmod +x scripts/install.sh scripts/start.sh scripts/verify.sh
./scripts/install.sh
./scripts/verify.sh              # first time: pass captcha
./scripts/start.sh               # start crawl
```

### Windows

Double-click `scripts/install.bat`, or in PowerShell:

```powershell
cd C:\path\to\crawlers\aliexpress-spider
.\scripts\install.bat
.\scripts\verify.bat             # first time: pass captcha
.\scripts\start.bat              # start crawl
```

### Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium
cp .env.example .env               # Windows: copy .env.example .env
```

## Configuration

### Categories

Edit `config/categories.yaml`:

```yaml
categories:
  - name: Beauty & Health
    url: https://www.aliexpress.us/category/66/beauty-health.html?SortType=total_tranpro_desc
```

### Elasticsearch (optional)

```env
ELASTICSEARCH_URL=http://user:password@host:9200
ELASTICSEARCH_INDEX=your_index_name
ELASTICSEARCH_BULK_CHUNK_SIZE=50
```

Leave `.env` empty or use `--no-es` to write JSONL only.

### Filter defaults

| Rule | Default |
|------|---------|
| Price | < $100 USD |
| Rating | >= 4.4 |
| Reviews | >= 1000 |
| Sold | >= 1000 |

## Usage

### Quick start (after install)

| Platform | Verify (once) | Start crawl |
|----------|---------------|-------------|
| Linux / macOS | `./scripts/verify.sh` | `./scripts/start.sh` |
| Windows | `scripts\verify.bat` | `scripts\start.bat` |
| Windows update | | `scripts\pull.bat` |

`start` uses headless mode, saved browser profile, and `--exit-on-block` by default. Output goes to `./data/`.

Extra crawl options are passed through:

```bash
./scripts/start.sh --max-pages 3 --max-products 20 --no-es
```

```powershell
.\scripts\start.bat --max-pages 3 --max-products 20 --no-es
```

### 1. Pass captcha once (recommended)

```bash
python -m aliexpress_spider verify --timeout 300
```

A visible browser opens. Complete the slider/captcha. Session is saved to `~/.aliexpress-spider/browser` (Windows: `%USERPROFILE%\.aliexpress-spider\browser`).

### 2. Crawl (headless, exit on block)

```bash
python -m aliexpress_spider crawl --no-es
```

Default behavior:

- Headless browser
- `--exit-on-block` — stop on first captcha/block page
- Uses saved profile from `verify` if present

### 3. Crawl after blocked (headed + manual wait)

```bash
python -m aliexpress_spider crawl \
  --headed \
  --no-exit-on-block \
  --captcha-wait 120 \
  --user-data-dir ~/.aliexpress-spider/browser
```

### Common options

```bash
python -m aliexpress_spider crawl \
  --max-pages 3 \
  --max-products 20 \
  --max-price 100 \
  --min-rating 4.4 \
  --min-reviews 1000 \
  --min-sold 1000 \
  --output-dir ./data \
  --categories config/categories.yaml
```

### Import JSONL to Elasticsearch

```bash
python -m aliexpress_spider import-es data/products_YYYYMMDD_HHMMSS.jsonl
```

## Output

Validated products are written to:

```
data/products_YYYYMMDD_HHMMSS.jsonl
```

Each line is a `StandardProduct` JSON object plus a `category` field. Multi-variant products include `options` and `variants`; description is cleaned HTML from the product page.

## Project layout

```
aliexpress-spider/
├── aliexpress_spider/       # Python package
│   ├── crawler.py           # Playwright crawl loop
│   ├── parser.py            # PDP data parser
│   ├── network.py           # API payload adapters
│   ├── formatter.py         # StandardProduct builder
│   ├── html_utils.py        # Description HTML cleanup
│   └── cli.py               # CLI entrypoint
├── config/categories.yaml
├── scripts/
│   ├── install.sh           # Linux / macOS installer
│   ├── install.ps1          # Windows PowerShell installer
│   ├── install.bat          # Windows batch installer
│   ├── verify.sh / verify.bat
│   ├── start.sh / start.bat # start crawl after install
│   ├── pull.bat             # pull latest code (Windows)
├── tests/
├── data/                    # Runtime output (gitignored)
├── .env.example
├── pyproject.toml
└── requirements.txt
```

## Anti-bot notes

AliExpress frequently shows captcha on detail pages. Recommended workflow:

1. Run `verify` in headed mode once per machine/profile
2. Crawl headless with `--exit-on-block`
3. If blocked, re-run `verify` then crawl with `--headed --no-exit-on-block`
4. Keep `--max-products` and `--max-pages` conservative

## Tests

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## GitHub（独立公开仓库）

本项目可以安全地作为 **public** 仓库发布。仓库内只有代码和 `.env.example` 占位符，**不会**包含真实密码。

### 绝不会提交的文件（已在 `.gitignore`）

| 文件 | 原因 |
|------|------|
| `.env` | Elasticsearch 账号密码 |
| `.venv/` | 本地 Python 环境 |
| `data/*.jsonl` | 抓取结果 |
| `*.log` | 运行日志 |
| `~/.aliexpress-spider/browser` | 浏览器会话（在用户目录，不在仓库内） |

推送前自检：

```bash
git status
git check-ignore -v .env .venv data/products.jsonl   # 应显示被 ignore
```

### 首次推送到你自己的 GitHub

在 Linux（或本机）：

```bash
cd /home/sky/src/crawlers/aliexpress-spider
git init -b main
git add .
git status                    # 确认没有 .env / .venv
git commit -m "Initial commit: AliExpress StandardProduct crawler"
git remote add origin git@github.com:YOUR_USER/aliexpress-spider.git
git push -u origin main
```

在 GitHub 网页新建仓库时选 **Public**，不要勾选 "Add README"（本地已有）。

### Windows 上克隆与更新

**第一次：**

```powershell
cd C:\src
git clone https://github.com/AriseshineSky/aliexpress-spider.git
cd aliexpress-spider
copy .env.example .env
# 编辑 .env，填入你自己的 ES 地址（仅本机，不进 git）
scripts\install.bat    # 必须执行：安装 em_product、playwright 等（git 不会装这些）
scripts\verify.bat
scripts\start.bat
```

**以后更新代码：**

```powershell
cd C:\src\aliexpress-spider
scripts\pull.bat
scripts\start.bat
```

依赖有变更时（`pyproject.toml` / `requirements.txt` 更新了）：

```powershell
scripts\pull.bat -Install
```

若 `git pull` 提示本地有改动，可先暂存：

```powershell
git stash
git pull
git stash pop
```

### 配置 Elasticsearch（仅本机）

复制模板后编辑，**不要提交 `.env`**：

```powershell
copy .env.example .env
notepad .env
```

```env
ELASTICSEARCH_URL=http://your-user:your-password@your-host:9200
ELASTICSEARCH_INDEX=your_index_name
```

## License

Proprietary — internal use unless otherwise specified.
