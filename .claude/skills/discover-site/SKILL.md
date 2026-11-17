---
name: discover-site
description: Khám phá sâu website, ghi network/API evidence và tạo artifact integration tái sử dụng.
---
# Discover site

Khi user cung cấp website mới:
1. Gọi script `python -m src.property_tool.discover <url> --out research/sites`.
2. Nếu cần khám phá tương tác, dùng Playwright MCP để click search/filter/pagination/detail và ghi các route quan trọng.
3. Không kết luận artifact active chỉ từ homepage; phải kiểm tra response/schema và tạo candidate.
4. Lưu `discovery.json`, `template.md`, `homepage.html`, screenshot/evidence vào `research/sites/<site-id>/`.
5. Trả report cho main agent gồm API-like requests, lỗi, route đã thử và flow chưa xác minh.
6. Candidate phải test và hỏi user trước khi promote active.
