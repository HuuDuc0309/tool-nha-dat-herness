# Tool nhà đất — Claude Code instructions

## Mục đích dự án

Đây là tool cá nhân chạy trong Claude Code để thu thập dữ liệu nhà đất từ một hoặc nhiều URL, chuẩn hóa dữ liệu về schema chung và xuất Excel nhiều sheet.

Mục tiêu chính là tìm mặt bằng, kho hoặc nhà xưởng cho thuê. Dữ liệu phải giữ lại đường dẫn nguồn để người dùng kiểm tra thủ công.

## Cách bắt đầu workflow

Skill dành cho end user:

```text
/bat-dau-tim-du-lieu
```

Khi user trigger skill chính:

1. Hiển thị các field mặc định hiện có trong `config/property-fields.json`.
2. Hỏi user muốn xuất field nào trong Excel; nếu user không chỉ định thì dùng field mặc định và đưa field đặc thù vào sheet thông tin bổ sung.
3. Nhận một hoặc nhiều URL.
4. Không pre-filter dữ liệu trước khi crawl trong MVP. Không loại bản ghi chỉ vì thiếu field.
5. Xác nhận ngắn phạm vi xử lý rồi bắt đầu crawl/parse/verify/export.
6. Luôn giữ URL nguồn trong kết quả.

Các skill kỹ thuật dành cho debug và vận hành:

- `/discover-site` — khám phá API, feed, search, detail và cấu trúc website.
- `/crawl-property` — chạy integration đã được duyệt để lấy dữ liệu.
- `/verify-property-data` — kiểm tra schema, evidence và mâu thuẫn.
- `/repair-site-artifact` — tạo candidate version khi parser/integration lỗi.
- `/export-property-data` — xuất workbook Excel.
- `/inspect-site-artifact` — kiểm tra artifact website.

## Quy tắc lọc dữ liệu

MVP hiện tại phải trích xuất toàn bộ dữ liệu trong phạm vi URL được cung cấp.

- Không đẩy filter xuống API để loại record.
- Không dùng prompt filter để loại record trước khi crawl.
- Excel phải giữ toàn bộ bản ghi parse được.
- User tự lọc trực tiếp trong Excel.
- Nếu user hỏi Claude phân tích sau khi dữ liệu đã có, có thể tạo báo cáo lọc riêng với các nhóm `đạt`, `chưa xác định` và `không đạt`.
- Bản ghi thiếu thông tin hoặc không chắc chắn phải giữ lại, gắn `Chưa xác định`, confidence và cảnh báo nếu có.
- Không tự chuyển `unknown` thành `false`.

## Schema và field

Schema mặc định nằm tại:

```text
config/property-fields.json
```

Không tự ý đổi key field đang tồn tại chỉ để làm đẹp tên hiển thị. Tên hiển thị tiếng Việt nằm ở thuộc tính `label`; key kỹ thuật dùng cho code và mapping.

Các field hiện tại gồm nhóm:

- Thông tin tin đăng: `title`, `source_url`, `source_site`.
- Vị trí: `address`, `province`, `district`, `ward`.
- Giá: `rent_amount`, `rent_period`, `deposit`.
- Diện tích: `land_area_m2`, `factory_area_m2`, `usable_area_m2`.
- Thông tin liên hệ: `contact`.
- Chất lượng xử lý: `extraction_status`, `confidence`, `warnings`.

Khi thêm field:

1. Thêm vào `config/property-fields.json`.
2. Dùng key tiếng Anh ổn định, label tiếng Việt dễ đọc.
3. Cập nhật mapping/template nếu field cần logic đặc thù.
4. Không làm mất dữ liệu hoặc đổi nghĩa field cũ.

## Artifact website

Artifact website nằm trong:

```text
research/sites/<site-id>/
```

Template chuẩn:

```text
research/templates/template.md
```

Mỗi integration nên có:

```text
template.md
integration.yaml
schema.json
discovery-report.md
test-results.json
versions/
regression/
```

`template.md` là tài liệu chuẩn để AI và human đọc. YAML/JSON là cấu hình có cấu trúc cho script chạy. Artifact đặc thù phải ghi trong mục `Special Notes` hoặc `Known Limitations`.

Không ghi credential thật vào report, template, Excel hoặc log. Nếu website cần đăng nhập, dùng browser profile/secret storage phù hợp và chỉ hỏi user khi authentication thất bại.

## Lifecycle integration

```text
candidate → tested → pending_approval → active → degraded → repair_candidate
```

Quy tắc:

- Integration mới phải test trước khi active.
- Parser-maintainer không được ghi đè active artifact một cách mù quáng.
- Repair phải tạo version candidate mới.
- Test regression trên snapshot cũ và mới trước khi promote.
- Nếu active parser lỗi, thử repair hữu hạn; nếu thất bại thì giữ version cũ/đánh dấu degraded và báo main agent.

## Agent và phân chia công việc

Khi triển khai orchestration:

- Main agent điều phối URL, queue, subagent, report và export.
- `site-explorer` khám phá website/API/browser flow.
- `data-extractor` lấy dữ liệu và mapping field.
- `data-verifier` kiểm tra structured extraction thông qua file path, không đẩy toàn bộ raw data vào main context.
- `parser-maintainer` tạo candidate repair và regression tests.

URL cùng domain có thể gom cho một subagent. Domain/route family khác nhau có thể chạy song song nhưng phải có giới hạn `max_parallel_subagents`; URL dư chạy qua queue/phases.

Một website lỗi không được chặn các website độc lập khác. Mỗi queue item phải có trạng thái cuối như `success`, `warning`, `needs_review`, `failed`, `blocked` hoặc `unsupported`.

## Excel output

Exporter phải tạo một file tổng hợp, tên cột ưu tiên tiếng Việt và giữ key kỹ thuật khi cần, ví dụ:

```text
Giá thuê (rent_amount)
Diện tích xưởng (factory_area_m2)
Đường dẫn gốc (source_url)
```

Workbook nên có các sheet:

- `Danh sách tin đăng` — toàn bộ record.
- `Chưa xác định` — field thiếu hoặc không đủ bằng chứng.
- `Bằng chứng dữ liệu` — source text/JSON, URL và confidence.
- `Cảnh báo` — lỗi/mâu thuẫn/giới hạn.
- `Báo cáo crawl` — trạng thái website, artifact và job.
- `Thông tin bổ sung` — custom field hoặc field đặc thù.
- `Tin nghi trùng` — chỉ đánh dấu, không tự gộp nếu chưa có quy tắc chắc chắn.

## Cấu trúc project

```text
.claude/skills/       Claude Code skills
config/               schema và config
src/property_tool/    CLI/pipeline
research/sites/       integration artifacts
research/jobs/        job/output
research/templates/   template dùng chung
Temp/                 browser profile, trace và file tạm
trash/                file rác tạm (tự xoá khi kết thúc phiên)
```

`research/jobs/`, `Temp/`, `trash/`, browser profile, snapshot và credential không được commit. Kiểm tra `.gitignore` trước khi tạo file lớn hoặc nhạy cảm.

## File rác trong lúc chạy

Mọi file sinh ra chỉ để debug trong lúc làm việc (script kiểm tra tạm, log trung gian, bản nháp, output thử nghiệm) phải đặt trong `trash/`, không đặt ở gốc project, `src/` hay `config/`.

Quy tắc:

- Tạo `trash/` nếu chưa có; đặt tên file mô tả mục đích (ví dụ `trash/export-check.txt`).
- `trash/` đã nằm trong `.gitignore` nên không bị commit.
- Không chuyển vào `trash/` các file là sản phẩm thật: `research/jobs/**`, `research/sites/**`, `config/**`, artifact, Excel.
- Không xoá thủ công cả thư mục `trash/` giữa lúc đang debug; hook `SessionEnd` trong `.claude/settings.json` tự dọn nội dung khi phiên kết thúc.

## Cài đặt và chạy

Windows:

```powershell
.\setup.ps1
```

Linux/macOS/Git Bash:

```bash
./setup.sh
```

Script bootstrap sẽ:

- Tạo `.venv`.
- Cài dependency trong `requirements.txt`.
- Cài Playwright và Chromium.
- Đăng ký Playwright MCP nếu có Claude CLI.
- Chạy smoke test tạo `Temp\smoke-test.xlsx`.

Chạy CLI thủ công:

```powershell
.\.venv\Scripts\python.exe -m src.property_tool.cli --urls-file urls.txt --output research\jobs\property-data.xlsx
```

Kiểm tra MCP:

```powershell
claude mcp list
```

MCP Playwright hiện được dùng cho browser discovery và tương tác website; CLI Python vẫn là phần data pipeline độc lập.

## Nguyên tắc phát triển

- Ưu tiên code deterministic cho fetch, retry, queue, schema, dedupe và export.
- Dùng AI cho discovery, semantic mapping, normalization và verification; không để AI âm thầm sửa production parser.
- Giữ raw evidence để audit và tạo regression case.
- Không bỏ qua lỗi; ghi rõ trạng thái, warning và đường dẫn artifact.
- Không chạy crawl rộng hoặc browser automation vượt phạm vi cần thiết.
- Tôn trọng điều khoản website, rate limit và cơ chế truy cập.
- Trước khi chạy request thật, xác nhận URL/domain và scope phù hợp.
- Sau mỗi thay đổi quan trọng, chạy smoke test hoặc test liên quan.
- Không commit secret, cookie, OAuth token, refresh token, browser profile hoặc raw data nhạy cảm.


## Nguyên tắc trả lời 
- Luôn luôn giải thích đơn giản, dễ hiểu, hạn chế dùng các khái niệm quá lạ, nếu phải dùng thì mô tả qua nó là gì đã rồi mới sử dụng khái niệm đó
- Hiện tại output trả về chỉ gồm 1 sheet chính, không trả về các thông tin không liên quan khác, nếu user cần thì sẽ tự yêu cầu sau. 

## Role của người dùng
**ROLE** : **USER**
- Nguyên tắc trả lời người dùng phụ thuộc vào role hiện tại của người dùng
- Nếu role người dùng là "user", thì mặc định trả lời siêu ngắn gọn, tuyệt đối không động gì đến technical, hãy nói đơn giản dễ hiểu. Ví dụ : thay vì bảo user : "hiện tại tool bị block do cơ chế antibot của cloudflared, tôi không bypass bặt hãy giải rồi báo tôi". Thì phải nói là : "Website batdongsan.com.vn có captcha tôi không giải được, bạn vui lòng giải captcha giúp tôi, giải xong thì không cần đóng trình duyệt cứ để đó tôi làm tiếp". Hãy nói ngắn gọn, dễ hiểu hết sức có thể. Tuyệt đối không dài dòng
- Còn nếu role hiện tại là "developer" thì mặc định trả lời như bình thường,  tuy nhiên vẫn chú trọng rule ở phần "## Nguyên tắc trả lời"
- Hiện tại đa phần người dùng chỉ quan tâm đến đất ở Hà Nội, nên tạm thời chỉ tìm kiếm dữ liệu nhà đất Hà Nội
- Với Role user, sẽ hỏi user lựa chọn các field suggest trước mặc định option là lựa chọn tất cả các field cố định đã được định nghĩa từ trước? cho tick chọn cái này thêm recommend vào., sau đó, cho checkbox tích chọn trong site đang có, sau đó đến bước bạn muốn thêm site nào không? nếu không thì bỏ qua
