# Facebook Story Automation — Android Control Plane

Hệ thống tự động chuẩn bị Facebook Page Story trên cloud và bàn giao việc thao tác Meta cho một điện thoại Android chuyên dụng.

## Kiến trúc hiện tại

```text
ChatGPT
  ↓
Google Sheet + Google Drive
  ↓
Railway control plane
  ↓ HTTPS + Android API token
Android Companion
  ↓ Accessibility, chỉ trong Meta Business Suite
Meta Business Suite trên điện thoại đã đăng nhập thủ công
```

**Railway không đăng nhập Facebook, không có cookie/session Meta và không mở Meta Business Suite.** Password, 2FA và session Facebook chỉ tồn tại trên điện thoại do người dùng tự đăng nhập.

## Phần cloud

Railway:

1. đọc job đến hạn từ `QUEUE`;
2. tự nhận diện IMAGE / VIDEO / TEXT;
3. áp dụng fixed link + random Link Text;
4. giữ source audio nếu có hoặc chọn nhạc approved theo policy;
5. render/chuẩn bị media;
6. upload media vào `02_MEDIA_READY`;
7. chuyển job sang `VALIDATED` với `ANDROID_READY:<Drive URL>`;
8. cung cấp API được bảo vệ bằng `ANDROID_API_TOKEN` cho điện thoại.

Android API sử dụng claim/lease để hạn chế double-processing. Media và result callback chỉ hợp lệ khi device id + claim token + lease đang đúng.

## Android Pilot Safe Mode

Bản pilot hiện tại là `0.2.1-pilot`.

Bản này cố ý chỉ được phép:

1. kiểm tra backend đang ở `ANDROID + DRY_RUN + PILOT_SAFE_MODE`;
2. claim một job đến hạn;
3. tải media đã chuẩn bị;
4. lưu media vào thư viện điện thoại;
5. mở Meta Business Suite;
6. click **duy nhất** control có exact label `Tạo tin / Create story`;
7. click **duy nhất** control `Ảnh/Video` nếu có;
8. dừng tại media picker và thu UI diagnostic.

Pilot **không chứa code** chọn thumbnail, Link Sticker hoặc Publish.

## Safety defaults

- `PUBLISH_TRANSPORT=ANDROID`
- `DRY_RUN=true`
- `ANDROID_PILOT_SAFE_MODE=true`
- API token tối thiểu 32 ký tự
- Android API token/claim token được lưu bằng Android Keystore
- backend URL được khóa trong app
- Android chỉ chấp nhận HTTPS
- Accessibility chỉ nhận event từ `com.facebook.pages.app`
- UI matching dùng exact label; 0 hoặc >1 match thì dừng
- không click theo tọa độ
- callback result idempotent với trường hợp response mạng bị mất
- claim có lease; lease hết hạn được recovery với retry accounting
- `PUBLISHED` là terminal state
- cloud runtime không cài Playwright/Chromium

## Fixed business defaults

Timezone: `Asia/Ho_Chi_Minh`

Default recruiting link:

```text
https://tuyendung.megas.vn/?ref=RE3ZHC
```

Không tự ý đổi domain, ref, thêm UTM, shorten hoặc normalize URL này.

## Quality gates

Backend CI bắt buộc:

```bash
python -m compileall -q app tests
python -m pytest -q
```

Android CI bắt buộc:

```bash
gradle -p android testDebugUnitTest
gradle -p android lintDebug
gradle -p android assembleDebug
```

APK chỉ được upload artifact khi cả unit test, lint và build đều pass.

## Chưa được coi là production-ready

Các blocker còn lại:

- chưa map chính xác thumbnail/media picker trên điện thoại thật;
- chưa map Link Sticker trên UI thật;
- chưa map bước xác nhận Story đã publish;
- chưa implement exact-time Android scheduler production;
- chưa chạy nhiều dry-run trên thiết bị thật;
- claim race hiện dựa trên một Railway replica + process lock; production multi-replica cần distributed CAS/database;
- media normalization H.264/AAC/9:16 cần hoàn thiện cho mọi input.

Không bật auto-publish cho tới khi các blocker trên được đóng.

## Secrets

Không commit vào GitHub:

- `ANDROID_API_TOKEN`
- Google OAuth credentials
- password/2FA Facebook
- Meta cookies/session
- Android claim token

Repo không cần và không được chứa Meta browser session.

## BA / QA

Xem `docs/BA_QA_CHECKLIST.md` để biết test matrix và production blockers đang được theo dõi.
