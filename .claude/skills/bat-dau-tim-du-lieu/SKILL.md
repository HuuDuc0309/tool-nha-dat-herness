---
name: bat-dau-tim-du-lieu
description: Discovery-first thu thập dữ liệu nhà đất từ nhiều website và xuất Excel.
---
# Bắt đầu tìm dữ liệu

## Nguyên tắc: crawl là đường chính, discovery là cứu hộ

Artifact đã kiểm tra là tài sản tái sử dụng. Mỗi lần đổi URL lại chạy discovery
toàn bộ website là lãng phí và tự tạo thêm challenge Cloudflare.

Thứ tự bắt buộc:

1. Hỏi field muốn xuất; hiển thị field mặc định từ `config/property-fields.json`.
2. Không gọi curl/HTTP extractor như output cuối ngay lập tức.
3. **Nếu site đã có artifact**: chạy smoke crawl nhỏ bằng `Crawler` trước
   (vài trang listing + vài detail, dùng `fetch()`). Smoke đạt thì crawl tiếp
   toàn phạm vi — **không** chạy discovery lại.
4. **Nếu site chưa có artifact**: chạy discovery đầy đủ
   `python -m src.property_tool.orchestrator <urls> --max-pages 20`,
   rồi mới crawl.
5. **Nếu smoke crawl thất bại** (0 card, 0 detail parse được, hàng loạt
   `fetch_failed`, hoặc layout đã đổi) hoặc artifact đã cũ so với yêu cầu:
   lúc đó mới revalidate/replay discovery, rồi thử crawl lại.
6. Artifact chỉ được promote **active** khi smoke crawl + completeness đều đạt.
7. Nếu gặp CAPTCHA/Cloudflare: tự chuyển sang headed browser để human xử lý,
   hiển thị action rõ ràng, chờ tối đa 300 giây, sau đó verify lại.
   Nếu vẫn lỗi, ghi `blocked`/`needs_review` và báo action cụ thể;
   không giả vờ crawl thành công.
8. Parse → verify → export Excel, giữ toàn bộ record và URL nguồn.

## Truy cập: ưu tiên fetch, giữ goto cho việc cần render

- Crawl listing/detail: `fetch()` trong trang đã qua kiểm tra, fallback `goto`.
- Discovery: `goto` chỉ để mở trang cần thao tác tương tác (form, filter, click,
  screenshot); mọi request đọc thêm dùng `fetch()`.
- Không bao giờ bypass Cloudflare: không solver, không giả fingerprint.

## Artifact

Lưu tại `research/sites/<site-id>/` gồm `manifest.json`, `discovery.json`, `template.md`, `discovery/`, routes, interactions, API candidates, response catalog, HTML và screenshot. Artifact là website knowledge base, không phải một curl response.

## Quy tắc

- Hãy giải CAPTCHA/Cloudflare trước (nếu gặp) rồi mới đi đến bước tiếp.
- Không lưu secret vào report/Excel.
- Không pre-filter dữ liệu trong MVP.
- Field thiếu ghi `Chưa xác định`, giữ record và evidence.
- Site không complete không được promote active.
- Không chạy lại discovery chỉ vì artifact tồn tại; chỉ chạy khi smoke crawl hỏng
  hoặc artifact thiếu phần cần dùng.
