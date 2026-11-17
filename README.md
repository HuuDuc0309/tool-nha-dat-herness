# Tool nhà đất

Công cụ cá nhân chạy trong Claude Code để thu thập dữ liệu nhà đất từ nhiều URL, chuẩn hóa về bộ trường chung và xuất Excel nhiều sheet.

## Trạng thái hiện tại

Phase 1 MVP đã có:

- Skill chính `/bat-dau-tim-du-lieu`.
- Các skill kỹ thuật: `discover-site`, `crawl-property`, `verify-property-data`, `repair-site-artifact`, `export-property-data`.
- Schema field mặc định tại `config/property-fields.json`.
- Template integration website tại `research/templates/template.md`.
- CLI tạo workbook Excel tại `src/property_tool/cli.py`.
- Các sheet Excel: danh sách tin đăng, chưa xác định, bằng chứng dữ liệu, cảnh báo và báo cáo crawl.

MVP hiện tại mới tạo record cơ bản từ URL. Discovery API, fetch HTML thật, Playwright và AI mapping sẽ được bổ sung ở các phase tiếp theo.

## Yêu cầu

- Windows 11.
- Python 3.10 trở lên.
- Claude Code nếu muốn dùng các skill trong `.claude/skills`.
- Node.js 18+ nếu cài Playwright MCP ở phase browser automation.

## Cài đặt nhanh

Clone repo về chạy một lệnh duy nhất:

**Windows (PowerShell):**

```powershell
.\setup.ps1
```

**Linux / macOS / Git Bash:**

```bash
./setup.sh
```

Script tự động:

- Tạo virtual environment.
- Cài deps Python, bao gồm Playwright.
- Tải Chromium cho Playwright.
- Đăng ký MCP Playwright với Claude Code.
- Chạy smoke test và tạo file Excel mẫu.

Sau khi chạy xong, có thể dùng tool ngay:

```powershell
.\.venv\Scripts\python.exe -m src.property_tool.cli --urls-file urls.txt --output research\jobs\property-data.xlsx
```

## Chạy CLI

Một URL:

```powershell
python -m src.property_tool.cli https://example.com --output Temp\smoke-test.xlsx
```

Nhiều URL:

```powershell
python -m src.property_tool.cli https://example.com/a https://example.com/b --output Temp\property-data.xlsx
```

Từ file URL, mỗi dòng một URL:

```powershell
python -m src.property_tool.cli --urls-file urls.txt --output research\jobs\property-data.xlsx
```

Nếu dùng virtual environment:

```powershell
.\.venv\Scripts\python.exe -m src.property_tool.cli --urls-file urls.txt --output research\jobs\property-data.xlsx
```

## Cài Playwright khi bắt đầu phase browser

Playwright chưa phải dependency bắt buộc của MVP hiện tại. Khi bắt đầu triển khai browser discovery, cài:

```powershell
python -m pip install playwright
python -m playwright install chromium
```

Không chạy browser automation trên website nếu chưa kiểm tra quyền truy cập, điều khoản sử dụng và giới hạn request phù hợp.

## MCP Playwright

`setup.ps1` / `setup.sh` tự đăng ký MCP Playwright ở scope project khi tìm thấy `claude` CLI:

```powershell
claude mcp add playwright -- npx -y @playwright/mcp@0.0.85 --browser chromium --user-data-dir E:/tool-nha-dat/Temp/browser-profile
```

Kiểm tra trạng thái:

```powershell
claude mcp list
```

Kết quả mong đợi:

```text
playwright: npx -y @playwright/mcp@0.0.85 --browser chromium --user-data-dir E:/tool-nha-dat/Temp/browser-profile - ✔ Connected
```

Nếu chưa thấy MCP Playwright, kiểm tra:

- Node.js 18+ đã cài (`node --version`).
- `claude` CLI có trong PATH (`claude --version`).
- Chạy `claude mcp list` để xem server có bị lỗi kết nối.
- Chạy lại đăng ký thủ công nếu cần:

```powershell
claude mcp remove playwright
claude mcp add playwright -- npx -y @playwright/mcp@0.0.85 --browser chromium --user-data-dir E:/tool-nha-dat/Temp/browser-profile
```

Sau khi thêm MCP, cần khởi động lại phiên Claude Code (hoặc chạy `/mcp`) để tool `browser_*` của Playwright xuất hiện.

Lưu ý: MCP server cần restart phiên Claude Code mới nhận cấu hình. Cấu hình MCP nằm trong `C:\Users\Admin\.claude.json` (scope local theo project), không nằm trong repository.

Browser profile, cookie, token và credential không được commit vào Git. Không đưa secret vào `template.md`, report hoặc Excel.

## Cấu trúc chính

```text
.claude/skills/       Các skill Claude Code
config/               Field schema và cấu hình runtime
src/property_tool/    Mã CLI và pipeline
research/sites/       Integration artifact theo website
research/jobs/        Job, report và output crawl
research/templates/   Template artifact chuẩn
Temp/                 File tạm, browser data và trace
```

## Quy tắc dữ liệu

- Crawl/extract toàn bộ dữ liệu trong phạm vi URL; không pre-filter ở MVP.
- Field thiếu hoặc không chắc chắn ghi `Chưa xác định`, không tự chuyển thành `false`.
- Luôn giữ URL nguồn để người dùng kiểm tra thủ công.
- Artifact mới phải test trước khi active.
- Artifact active được version hóa; repair tạo candidate mới.
- Raw snapshot, credential, browser profile và file Excel tạm không commit.

## Kiểm tra nhanh

```powershell
python -m src.property_tool.cli https://example.com --output Temp\smoke-test.xlsx
Test-Path Temp\smoke-test.xlsx
```

## Lộ trình tiếp theo

1. Fetch HTML và JSON-LD bằng HTTP.
2. Thêm Playwright discovery cho trang render bằng JavaScript.
3. Lưu site registry và integration artifact.
4. Thêm queue/subagent orchestration.
5. Mapping field từ dữ liệu thật và lưu evidence.
6. Verify schema/cross-field.
7. Tạo Excel đầy đủ từ dữ liệu đã crawl.
