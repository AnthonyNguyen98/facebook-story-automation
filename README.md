# Facebook Story Automation Worker v1

Worker cho workflow đăng Facebook Page Story qua Meta Business Suite Web.

## Luồng

1. ChatGPT nhận ảnh/video/text + ngày giờ.
2. File source được lưu vào Google Drive `01_MEDIA_INBOX`.
3. Job được ghi vào tab `QUEUE` của Google Sheet.
4. Worker Railway poll queue theo `Asia/Ho_Chi_Minh`.
5. Worker tự nhận diện IMAGE / VIDEO / TEXT.
6. Nếu video đã có audio: giữ nguyên.
7. Nếu source im lặng: chọn nhạc approved từ `MUSIC_CATALOG` theo pool và render bằng ffmpeg.
8. Worker upload media đã chuẩn hóa vào `02_MEDIA_READY`.
9. Playwright mở Meta Business Suite, tạo Story, gắn link mặc định, random LINK_TEXT và publish.
10. `QUEUE` + `LOGS` được cập nhật; lỗi retry tối đa 3 lần, cách nhau 120 giây.

## Safety defaults

- `DRY_RUN=true` mặc định: worker dừng trước nút Publish.
- `LINK_LOCKED=true` ở CONFIG: link khác DEFAULT_LINK sẽ bị từ chối.
- Nhạc chỉ được chọn khi `SOURCE=META_SOUND_COLLECTION`, `LICENSE_STATUS=APPROVED`, `APPROVED=TRUE`.
- UI selector fail thì worker fail-safe và retry, không click theo tọa độ.

## Cần hoàn tất một lần trước production

1. Tạo Google service account, share folder/project Drive + Control Sheet cho service account.
2. Điền `GOOGLE_SERVICE_ACCOUNT_JSON` trên Railway.
3. Bootstrap Meta session bằng `scripts/bootstrap_meta_session.py`, đưa storage state vào Railway volume hoặc `META_STORAGE_STATE_B64`.
4. Map/verify selector thực tế của Meta Business Suite account bằng `DRY_RUN=true`.
5. Điền `DEFAULT_PAGE` / `META_BUSINESS_URL` đúng Fanpage.
6. Nạp các track Meta Sound Collection đã duyệt vào `MUSIC_CATALOG` và Drive Music Library.
7. Chuyển `DRY_RUN=false` sau khi test Story thành công.

## Local check

```bash
python -m compileall app scripts
python -m pytest -q
```

## Railway

Project đã được tạo: `facebook-story-automation`.
Sau khi repo GitHub được kết nối, deploy branch `main`, set env vars và mount persistent storage cho `/data` nếu dùng file session.
