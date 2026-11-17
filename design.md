# Thiết kế: session browser + thang nguồn dữ liệu

Trạng thái: **đã chốt hướng, chưa triển khai**
Ngày chốt: 2026-11-17
Quyết định: **Phương án B** — làm bậc HTTP + probe trước; bậc API để sau khi tìm được endpoint thật.

---

## 1. B cam kết gì

| # | Cam kết | Trạng thái |
|---|---|---|
| 1 | Một session browser cho cả lượt chạy, không mở/đóng theo từng link | **ĐÃ CODE + test** (`session.py`, `discover.py`, `phase_explorer.py`, `orchestrator.py`, `crawler.py`) |
| 2 | Thang nguồn dữ liệu tính **theo từng luồng** (danh sách / chi tiết), có probe kiểm chứng | Chưa code — chưa có `ladder.py` |
| 3 | Bậc `http` dùng được cho bds365 ở cả danh sách lẫn chi tiết | Chưa code; bằng chứng n=1 mỗi luồng |
| 4 | Runtime chạy theo `integration.yaml`, AI chỉ can thiệp khi probe fail | Chưa code |
| 5 | Site cùng platform phải chạy 1 mẫu conformance trước khi tin | Chưa code |

### 1.1 Đã kiểm chứng session (2026-11-17)

Test offline có browser thật (`Temp/test_session.py`):

```text
site-a: 1 context, 1 work page reused across 8+ calls   OK
site-b: separate context and page                       OK
work page re-created, context preserved                 OK
close() idempotent                                      OK
closed runtime raises RuntimeError                      OK
is_challenge('Chờ một chút...') -> True                 OK
is_challenge('Kho, nhà xưởng cho thuê') -> False        OK
```

Điều này chứng minh tái sử dụng session **trong cùng một process/lượt chạy**. Nó **không** chứng minh một session sống qua nhiều lượt chạy hoặc giữ được Cloudflare clearance vô thời hạn.

## 2. B **không** cam kết gì — phải nói rõ

| Điều | Sự thật |
|---|---|
| **Không** mang lại việc dùng API | Chưa tìm được endpoint JSON nào trả dữ liệu tin đăng. Bậc `api` tồn tại trong thiết kế nhưng ở trạng thái `untested`. |
| **Không** giảm tải cho `batdongsan.com.vn` | Toàn bộ bằng chứng HTTP là trên `batdongsan365.vn`. bds.com.vn có Cloudflare — HTTP thô nhiều khả năng bị chặn. Chưa test. |
| **Không** hoàn tất yêu cầu "ưu tiên API" | Yêu cầu đó được đáp ứng về **cấu trúc** (thang có bậc api đứng đầu), chưa đáp ứng về **chức năng**. |

Nếu sau này tìm được API, chỉ cần thêm một entry vào `integration.yaml` và cho probe chạy — không phải sửa lại kiến trúc.

---

## 3. Bằng chứng hiện có

### 3.1 Luồng chi tiết — bds365

Cùng một URL chi tiết, lấy **HTTP thô không mở browser**, chạy đúng parser hiện tại, so với snapshot browser:

```text
URL: .../cho-thue-kho-xuong-...-bs15426/
12 field so sánh: title, address, price_text, area_text, legal, direction,
                  listing_code, posted_at, expires_at, post_type, contact,
                  property_type
Kết quả: 0 khác biệt
description: 956 ký tự == 956 ký tự
attributes : 7 == 7
```

### 3.2 Luồng danh sách — bds365

Danh mục `cho-thue-kho-nha-xuong`, trang 1:

```text
HTTP thô      : 3 card
Browser render: 3 card
Tiêu đề 3 card: giống hệt từng chữ
```

### 3.3 Giới hạn của bằng chứng — đọc trước khi tin

| Giới hạn | Ý nghĩa |
|---|---|
| **n = 1 mỗi luồng** | Một trang chi tiết, một trang danh sách. Chưa loại trừ may mắn. |
| **Chỉ bds365** | bds.com.vn chưa test HTTP lần nào. |
| **Danh mục nhỏ** | `kho-nha-xuong` chỉ có 3 tin — không chứng minh được phân trang HTTP đúng. |
| **Chưa test P3 ở quy mô** | Chưa so 20–50 cặp URL. |

### 3.4 Về API — những gì đã quan sát

Traffic bắt được trong browser, không phải chủ động đi tìm:

| Site | XHR/fetch | Là dữ liệu tin đăng? |
|---|---|---|
| batdongsan365.vn | `cdn-cgi/rum`, `api/address-search/` | Không |
| batdongsan.com.vn | survey, ảnh tĩnh, `bff-seller/users/main-info`, `GetCurrentUserInfo`, banner | Không |

**Cách đọc đúng:** "chưa thấy" ≠ "không tồn tại". Chưa hề bấm phân trang/lọc/sắp xếp trong lúc ghi network. Một site render sẵn ở server (như bds365, chi tiết đủ dữ liệu trong HTML thô) **có thể không có API JSON nào**.

### 3.5 Cập nhật: probe có phân trang (2026-11-17)

Chạy `api_probe.py`, đi đúng luồng danh sách → phân trang → chi tiết, trong cùng session:

| Site | Danh sách | Phân trang | Chi tiết | JSON trả dữ liệu tin |
|---|---|---|---|---|
| batdongsan365-vn | 20 card | `?page=2` | parse OK | **0** |
| batdongsan-com-vn | 20 card | `/p2` → **tin khác** (`results_changed: true`) | parse OK | **0** |

Các endpoint JSON bắt được trên bds.com.vn đều **không** trả danh sách tin đăng:
`ProductSearch/GetTopProAgentV2` (top agent), `ProductListing/GetVideoListingsData`
(video), `Origins/CommonData/HasPricingHistoryChart` (trả về `bool`).
Danh sách tin **nằm trong HTML** của trang `/p2`, không phải trong một API.

→ Kết luận có giới hạn: **chưa có bằng chứng API dữ liệu tin đăng tồn tại** trên cả hai site.
Bậc `api` vì vậy vẫn `untested`; triển khai hiện dùng HTTP/browser.

Một lỗi thật đã sửa nhờ probe này: `bds.com.vn` phân trang bằng `/p2` (233 trang),
không phải `?page=`. Pattern cũ chỉ nhận `?page=` nên **site đó bị giới hạn ở trang 1**.

### 3.5 Lỗi đã sửa trong quá trình brainstorm

Tôi từng kết luận *"HTTP chỉ trả 3 card, browser render 20 card → danh sách bắt buộc phải dùng browser"*.

**Sai.** Đó là so HTTP danh mục `kho-nha-xuong` với browser danh mục `cua-hang-ki-ot`. Hai danh mục khác nhau, kích thước khác nhau. So đúng cùng danh mục: 3 == 3.

Hệ quả: lý do "danh sách phải dùng browser" **không có cơ sở**. Bậc HTTP được xét cho **cả hai** luồng.

Bài học ghi lại: đây chính là loại lỗi mà probe P3 phải chặn — so sánh phải do code làm trên cùng URL, không do mắt người.

---

## 4. Session browser — một chủ sở hữu

### 4.1 Nguyên nhân hiện tại (đã xác minh trong code)

| # | Vị trí | Vấn đề |
|---|---|---|
| 1 | `phase_explorer.py:16` | 4 phase, mỗi phase tự `chromium.launch()` và tự `close()` |
| 2 | `discover.py:25` | `explore()` mở thêm browser thứ 5 cho cùng site |
| 3 | `crawler.py:232,242` | Mỗi request `new_page()` rồi `close()` ngay |
| 4 | — | Khi tab cuối đóng, cửa sổ biến mất → lượt sau mở lại |

Hệ quả: 5 lần khởi tạo browser cho một website trong một lượt discovery; Cloudflare clearance không được chia sẻ giữa các phase; người dùng thấy cửa sổ nhấp nháy.

### 4.2 Thiết kế

```text
SessionRuntime                      một cho toàn bộ lượt chạy
├── Playwright driver               khởi tạo 1 lần
├── SiteSession[site_id]
│   ├── context                     persistent (có profile) | ephemeral
│   ├── anchor_page                 tab neo, KHÔNG BAO GIỜ đóng
│   └── challenge_solved_at
└── page theo request               mở/đóng tự do — cửa sổ không sập
```

**Tab neo là điểm cốt lõi.** Mở `anchor_page` ngay sau khi tạo context, giữ suốt lượt chạy. Mọi tab con đóng thoải mái; cửa sổ vẫn tồn tại. Đây là thứ trực tiếp sửa lỗi bạn quan sát.

### 4.3 Quy tắc bắt buộc

| Quy tắc | Lý do |
|---|---|
| Mỗi site một context riêng | Cookie/localStorage không lẫn giữa domain |
| Không tái tạo context persistent | Mất Cloudflare clearance |
| Ưu tiên tự giải nếu không có khả năng thì mới nhờ người giải, nỗ lực hết sức để làm  Challenge → `blocked`, xin người giải |
| Đóng context khi kết thúc run (hoặc `--keep-open`) | Cho phép kiểm tra thủ công |

---

## 5. Thang nguồn dữ liệu — theo từng luồng

```yaml
flows:
  listing:
    ladder: [api, http, browser]
  detail:
    ladder: [api, http, browser]
```

Cả hai luồng cùng thang, vì bằng chứng §3.2 cho thấy HTTP đủ cho danh sách trên bds365. Thang **giống nhau về hình dạng** nhưng **trạng thái từng bậc khác nhau theo site**.

### 5.1 Trạng thái bậc

| Trạng thái | Nghĩa | Được dùng làm nguồn chính? |
|---|---|---|
| `verified` | Đã chạy probe, khớp schema | Có |
| `untested` | Có khai báo, chưa kiểm chứng | **Không** |
| `degraded` | Từng verified, nay lệch | Không — tự xuống bậc |
| `blocked` | Challenge hoặc cần xác thực | Không |

### 5.2 Dự kiến trạng thái ban đầu

| Site | listing | detail |
|---|---|---|
| batdongsan365-vn | `api: untested` · `http: cần probe` · `browser: verified` | `api: untested` · `http: cần probe` · `browser: verified` |
| batdongsan-com-vn | `api: untested` · `http: untested (Cloudflare)` · `browser: verified` | như trên |

Chỉ sau khi probe pass thì `http` mới lên `verified`.

### 5.3 Chống thử-và-lỗi lặp lại

Không thử API cho từng bài rồi mới chuyển HTTP. Mỗi luồng **chọn bậc một lần** ở đầu lượt, dựa trên trạng thái trong `integration.yaml`. Bậc `degraded` trong lượt chạy → ghi cảnh báo, xuống bậc kế, và **hạ trạng thái cho lượt sau**.

---

## 6. Conformance probe — P0 đến P4

Chạy bằng code, không bằng mắt. Bắt buộc trước khi một bậc được lên `verified`, và bắt buộc khi gặp site mới cùng platform.

| Mức | Kiểm gì | Fail nghĩa là | Chặn? |
|---|---|---|---|
| **P0** | Kết nối được, không bị challenge | `blocked` | Có |
| **P1** | Response đúng cấu trúc mong đợi (JSON keys / HTML markers) | API đổi hoặc sai platform | Có |
| **P2** | Parser ra ≥1 listing (title+url+price) và ≥1 detail (title+address+area) | Parser không khớp site | Có |
| **P3** | **Parity:** cùng URL, so bậc ưu tiên với browser | Nguồn ưu tiên thiếu dữ liệu âm thầm | Có |
| **P4** | Chạy mẫu thứ 2 (khác danh mục) | Chỉ đúng ở 1 trang | Cảnh báo |

**P3 là mức quan trọng nhất.** Nó là thứ duy nhất bắt được kiểu lỗi "trang trả về trông bình thường nhưng thiếu 17/20 tin". Không có P3 thì không được nâng bậc.

### 6.1 P3 so cái gì

```text
Với mỗi cặp URL mẫu:
  A = parse(nguồn ưu tiên)      ← http hoặc api
  B = parse(browser)
  So: số record, và từng field trong tập bắt buộc
  Fail nếu: |A| < |B| * threshold   hoặc   bất kỳ field bắt buộc nào khác
```

Với luồng danh sách, `số record` là số card. Đây chính là phép so tôi làm sai bằng mắt ở §3.5.

### 6.2 Kết quả phân nhánh

```text
P0..P3 pass   → status: active,         0 can thiệp AI
chỉ P2 pass   → status: needs_review,   AI xem 1 mẫu, sửa mapping
P0/P1 fail    → status: degraded,       xuống bậc kế
```

---

## 7. Tái sử dụng: AI một lần, runtime nhiều lần

### 7.1 Nguyên tắc

Runtime **không đọc HTML bằng AI**. AI chỉ ghi `integration.yaml`; sau đó mỗi lượt crawl chỉ là "đọc YAML → fetch → parse".

```yaml
# research/sites/batdongsan365-vn/integration.yaml  (dự kiến)
site_id: batdongsan365-vn
platform: batdongsan_group
session: { mode: ephemeral }

flows:
  detail:
    ladder:
      - kind: api
        status: untested
      - kind: http
        url_template: "{card_url}"
        parser: batdongsan_group.parse_detail
        status: untested          # → verified sau khi P3 pass
        verified_at: null
        evidence: { samples: 1, fields_matched: 12, compared_with: browser }
      - kind: browser
        url_template: "{card_url}"
        content_ready: ["h1", "div.property-content"]
        parser: batdongsan_group.parse_detail
        status: verified
```

### 7.2 Ai làm gì

| Bước | Ai | Ra cái gì |
|---|---|---|
| Research site mới | AI, một lần | draft `integration.yaml` |
| Conformance P0–P4 | Code | `conformance.json` pass/fail |
| Crawl hằng ngày | Code | record |
| Parser hỏng | Code báo `degraded` → AI repair | `repair_candidate` |

Điểm mấu chốt: **AI không có mặt trong vòng lặp crawl.**

### 7.3 Kiến thức dùng chung cho site cùng họ

```text
research/platforms/<platform>/profile.yaml     parser, marker, cấu trúc chung
research/sites/<site-id>/integration.yaml      phần riêng + kết quả probe
```

`batdongsan365.vn` và `batdongsan.com.vn` **cùng platform nhưng khác template chi tiết** (`h1.h2` + `p.b2` so với `re__pr-title`) → không tin nhau vô điều kiện. Site mới cùng platform **bắt buộc chạy P0–P4** trước khi active.

---

## 8. Cấu trúc file dự kiến

```text
config/sites.json                                 site + platform + profile
research/platforms/<platform>/profile.yaml        kiến thức dùng chung
research/sites/<site>/integration.yaml            thang + trạng thái từng bậc
research/sites/<site>/conformance.json            kết quả probe + sample

src/property_tool/session.py     (MỚI)  SessionRuntime, anchor page
src/property_tool/ladder.py      (MỚI)  chọn bậc, fallback, phát hiện drift
src/property_tool/sources/api.py     (MỚI)
src/property_tool/sources/http.py    (MỚI)
src/property_tool/sources/browser.py (MỚI)
src/property_tool/probe.py       (MỚI)  conformance P0–P4
src/property_tool/crawler.py     SỬA   dùng ladder thay vì gọi browser trực tiếp
```

---

## 9. Thứ tự triển khai

| # | Việc | Vì sao thứ tự này | Cách đo |
|---|---|---|---|
| 1 | `SessionRuntime` + anchor page | Sửa đúng cái người dùng thấy; rẻ nhất | 5 lần mở browser → 1 |
| 2 | `ladder.py` + `integration.yaml`, **chỉ bậc browser** | Không đổi hành vi, chỉ thay lớp quyết định | Output phải **giống hệt** run cũ, từng field |
| 3 | `probe.py` P0–P4 | Cần có trước khi tin bậc mới | Bắt được lỗi kiểu §3.5 |
| 4 | Bậc `http` cho bds365, mở rộng mẫu lên ≥20 cặp URL | Chứng minh ngoài n=1 | P3 pass trên ≥20 cặp |
| 5 | `http` cho bds.com.vn — **chỉ khi** P0 pass | Cloudflare có thể chặn hoàn toàn | P0 pass/fail |
| 6 | Bậc `api` — chỉ khi tìm được endpoint | Chưa có bằng chứng tồn tại | P1 + P3 pass |

Bước 2 là bước an toàn nhất để bắt đầu: chạy lại cùng tham số, so từng record với Excel hiện có. Khác một field là dừng.

---

## 10. Rủi ro

| Rủi ro | Xử lý |
|---|---|
| HTTP "trông ổn" nhưng thiếu dữ liệu | Bắt buộc P3 parity; không có P3 thì không nâng bậc |
| Session sống lâu → Cloudflare hết hạn | Phát hiện challenge → `blocked`; không coi là thành công |
| Memory tăng khi giữ context lâu | Chỉ tái tạo context ephemeral |
| Dùng chung context 2 domain | Cấm; mỗi site một context |
| API nội bộ đổi không báo trước | P1 schema probe mỗi lượt; fail → `degraded` |
| bds.com.vn chặn HTTP hoàn toàn | Giữ bậc browser làm nguồn chính cho site đó |

---

## 11. Không làm

- Ưu tiên tự giải Cloudflare  nếu không có khả năng thì mới nhờ người giải, nỗ lực hết sức để làm Cloudflare.
- Không bấm "Hiện số" để lấy SĐT đầy đủ.
- Không gọi endpoint cần xác thực trái phép hoặc vượt điều khoản.
- Không dùng chung context giữa hai domain.
- Không tự gộp tin nghi trùng.
- Không nâng bậc `http`/`api` lên `verified` khi chưa có P3 pass.