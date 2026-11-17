# Site Integration — batdongsan.com.vn

## Overview

- Site ID: `batdongsan-com-vn`
- Domain: `batdongsan.com.vn`
- Status: `tested` — chưa promote `active`
- Version: `1.0.0`
- Platform: `batdongsan_vn` (template detail mới `re__pr-*`)
- **Đây là nguồn dữ liệu chính**: 15.990 tin cho thuê Hà Nội và 32.682 tin TP.HCM (2026-11-17)

## Domain and Route Families

| Route family | Pattern | Ví dụ |
|---|---|---|
| Category listing | `/{category}` | `/cho-thue-kho-nha-xuong-dat` |
| Pagination | `/{category}?page={n}` | `/cho-thue-van-phong?page=2` |
| Detail | `/{category}-{slug}-pr{id}` | `/cho-thue-kho-nha-xuong-dat-xa-phuoc-hoa/...-pr46537039` |
| Microservice router | `/microservice-architecture-router/...` | `Systems/Home/GetInterestedProductsBinnova` |
| Seller BFF | `api.batdongsan.com.vn/bff-seller/...` | 401 khi chưa đăng nhập |

## Supported Flows

- ✅ Listing (20 card/trang, `prid`/`uid` có trong attribute card)
- ✅ Pagination
- ✅ Detail: title, address 2 dòng, short-info (giá/dt/ngày/code), specs, mô tả
- ⚠️ Cloudflare: **bắt buộc** human giải challenge một lần; session lưu trong persistent profile
- ❌ Phone reveal (`Hiện số` là action tương tác — tool không thực hiện)
- ❌ Login-gated seller data

## API / Feed Discovery

Không có listing/detail JSON API công khai. Đã thấy:

| Endpoint | Status | Ghi chú |
|---|---|---|
| `/microservice-architecture-router/Systems/Account/GetCurrentUserInfo` | 200 | session/posthog, không chứa tin |
| `/microservice-architecture-router/Systems/Home/GetInterestedProductsBinnova` | 200 | gợi ý tin, không dùng crawl |
| `api.batdongsan.com.vn/bff-seller/users/main-info` | 401 | cần đăng nhập |
| `/user-management-service/api/v1/User/RefreshToken` | 401 | cần đăng nhập |
| `t.batdongsan.com.vn/api/surveys/` | 200 | tracking survey |

HTML là nguồn chính; các API trên là internal và không đủ để lấy listing.

## Request Parameters

Listing: `?page={n}` (bắt đầu 1). Không có filter bắt buộc.
Detail: `pr{id}` chính là listing id.

## Response Schema

Không JSON-LD, không embedded JSON. Toàn bộ nội dung nằm trong `div.re__pr-info`:

```
h1.re__pr-title
span.re__address-line-1   → địa chỉ trước sáp nhập
span.re__address-line-2   → tên sau sáp nhập, vd "(Xã Phước Hòa, Hồ Chí Minh mới)"
div.re__pr-short-info-item > span.title / span.value
    Khoảng giá | Diện tích | Ngày đăng | Ngày hết hạn | Loại tin | Mã tin
div.re__pr-specs-content-item > …-title / …-value   → thuộc tính thêm
div.re__detail-content                               → mô tả tự do
disclaimer text                                       → "Mã tin 46537039"
```

## Field Mapping

| Field schema | Nguồn |
|---|---|
| `title` | `h1.re__pr-title` |
| `address` | `re__address-line-1` (dòng 2 lưu riêng vào `address_alt`, **không gộp**) |
| `province`/`district`/`ward` | tách từ `address` |
| `rent_amount` | `Khoảng giá` → VND, chỉ khi là giá tổng |
| `price_per_m2_vnd` | khi `Khoảng giá` chứa `/m²` → đây chính là giá/m² |
| `usable_area_m2` | `Diện tích` |
| `contact` | số broker bị mask trong mô tả (`0937 992 ***`) + `contact_masked=yes` |
| `listing_code` | `Mã tin` |
| `posted_at` / `expires_at` / `post_type` | `Ngày đăng` / `Ngày hết hạn` / `Loại tin` |

## Extraction Strategy

1. Mở persistent profile (`Temp/bds-profile`) headed; nếu gặp challenge → chờ human giải (tối đa `--wait-human`).
2. Crawl listing, thu `div.js__card-full-web`, lấy detail URL.
3. Parse detail bằng `adapters/batdongsan_vn.py:parse_detail()`.
4. Normalize giá: nhận diện `/m²` → tách khỏi `rent_amount`.
5. Lưu snapshot HTML.

## Authentication

Không cần đăng nhập cho nội dung công khai. Cloudflare không phải auth nhưng cần
session trình duyệt thật — giải thủ công một lần, profile giữ lại.

## Test Results

`2026-11-17`:

- Cloudflare: human giải thành công, session tái sử dụng được cho lượt crawl sau (persistent profile).
- Detail parse đầy đủ: title, address 2 dòng, Khoảng giá, Diện tích, Ngày đăng, Ngày hết hạn, Loại tin, Mã tin, mô tả.
- Giá theo m² (`52,6 nghìn/m²`) được tách đúng → `rent_amount` trống, `price_per_m2_vnd` = 52600, có warning.
- Giá tổng (`30 triệu/tháng`) → `rent_amount` = 30000000.
- Số điện thoại mask giữ nguyên + warning rõ ràng; không bịa số.
- `11.000 m²` / `2.000 m²` / `957,9 m²` parse đúng.

## Known Limitations

- Cần human giải Cloudflare trước khi crawl (mỗi lần profile hết hạn).
- Số liên hệ broker bị mask; cần bấm "Hiện số" — tool không làm.
- Đất/xưởng báo giá theo m² → không có tổng giá thuê tháng.
- `deposit`, `frontage_m` không có trên template này.
- Discovery heuristic báo `listing_detail: false` (false negative — URL detail kết thúc `-pr<id>`).
- Listing page ~1,3 MB HTML/trang (map payload + 20 card) → snapshot chiếm dung lượng, chỉ giữ để audit.

## Special Notes

- `prid` trong attribute card là listing id chuẩn, đáng tin hơn parse URL.
- Địa chỉ có 2 dòng do sáp nhập tỉnh 2025: dòng 1 là địa chỉ cũ, dòng 2 là tên mới. Giữ riêng để không mất ngữ cảnh.
- Profile Cloudflare nằm ở `Temp/bds-profile` (đã gitignore). Xoá thư mục đó để reset.

## Fallback Scripts

```bash
# crawl (cần headed cho lần đầu / khi challenge hết hạn)
.\.venv\Scripts\python.exe -m src.property_tool.crawler --sites batdongsan-com-vn --out research/jobs/<job> --headed --max-listing-pages 3 --max-details 200 --delay 1.5

# xuất Excel
.\.venv\Scripts\python.exe -m src.property_tool.exporter research/jobs/<job>
```

## Version History

| Version | Date | Change |
|---|---|---|
| 1.0.0 | 2026-11-17 | Integration đầu tiên cho template `re__pr-*`, persistent profile cho Cloudflare |