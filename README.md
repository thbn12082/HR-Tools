# Argon 6-Extension Orchestrator & AdsPower 20-Profile Manager (`HR-Tools`)

> **TÀI LIỆU BÀN GIAO CHO ARGON TRÊN MÁY MỚI (HANDOVER BRIEF)**  
> File này được viết để instance Argon trên máy tiếp theo nắm toàn bộ bối cảnh chiến thuật, hạ tầng công cụ, kiến trúc code đã triển khai và những việc cần làm tiếp mà không phải hỏi lại từ đầu.

---

## 1. Bối cảnh & Hạ tầng thực tế đang sử dụng

1. **Trình duyệt chống Fingerprint**:
   - Sử dụng **AdsPower** với **20 Profile trình duyệt ảo** (`acc_1` $\rightarrow$ `acc_20`).
   - Toàn bộ phần chống fingerprint (Canvas, WebGL, Audio, User-Agent, WebRTC...) **đã do AdsPower đảm nhiệm ở tầng nhân Chromium**.
   - **Quy tắc cho Argon**: Không nhồi thêm code giả lập GPU/Canvas/Fingerprint vào trong Extension nữa để tránh xung đột với AdsPower và tránh làm nặng trình duyệt.

2. **Tài khoản & 6 Extension tìm thông tin ứng viên**:
   - Có **20 tài khoản Gmail** tương ứng với 20 Profile AdsPower. Mỗi Profile đăng nhập đồng thời vào `LinkedIn` và **6 công cụ (cài trực tiếp bản gốc từ Chrome Web Store)** với định mức Credit thực tế như sau:

| Công cụ (Extension) | Định mức Credit mỗi Profile | Tổng vốn 20 Profile | Quy tắc trừ Credit & Vai trò chiến thuật |
| :--- | :--- | :--- | :--- |
| **1. ContactOut** | **5 lượt / ngày** *(tự hồi mỗi 24h)* | **100 lượt / ngày** *(~3.000/tháng)* | Trả về cả Email + SĐT. Vì hồi mỗi ngày nên luôn ưu tiên dùng trước. |
| **2. Kendo Ninja** | **50 credit / tháng** | **1.000 credit / tháng** | Mỗi Email tìm thấy mất **1 credit**. |
| **3. Apollo.io** | **80 credit / tháng** | **1.600 credit / tháng** | Tìm Email mất **1 credit**, nhưng tìm SĐT mất tới **8 credit**. |
| **4. Snov.io** | **50 credit / tháng** | **1.000 credit / tháng** | Mạnh về Email công ty (Work Email), **1 credit/lượt**. |
| **5. Lusha** | **40 credit / tháng** | **800 credit / tháng** | Mạnh về cả SĐT lẫn Email. |
| **6. SignalHire** | **10 credit / tháng** | **200 credit / tháng** | **Cực hiếm (chỉ 10 lượt/tháng)** $\rightarrow$ **TUYỆT ĐỐI KHÔNG CHẠY TỰ ĐỘNG**. Chỉ dùng để người dùng tự bấm tay ("cứu nét") cho các ca khó không tìm được SĐT. |

3. **Môi trường mạng & Khối lượng chạy mỗi ngày**:
   - Đang dùng **mạng công ty (1 địa chỉ IP tĩnh chung)**, chưa cắm USB 4G xoay IP.
   - Khối lượng mục tiêu: **~50 link LinkedIn / ngày**.
   - **Quy tắc sống còn trên mạng công ty**: Chạy **tuần tự từng Profile một** (tuyệt đối không mở nhiều Profile chạy song song cùng lúc trên 1 IP công ty).

---

## 2. Kiến trúc hệ thống đã triển khai (Cách 1)

Thay vì bung source và sửa mã nguồn của cả 6 Extension riêng lẻ, dự án sử dụng kiến trúc **Cách 1 (1 Master Extension điều phối chung + 1 Local Python Server)**:

### A. Cấu trúc thư mục dự án
- [`argon_server.py`](./argon_server.py): Máy chủ điều phối trung tâm + Giao diện Web Dashboard chạy tại `http://127.0.0.1:8765`.
- [`Argon_Collector/`](./Argon_Collector): Extension điều phối duy nhất nạp kèm vào các Profile AdsPower:
  - [`manifest.json`](./Argon_Collector/manifest.json): Manifest V3, tiêm script vào `MAIN` world của cả trang LinkedIn lẫn toàn bộ iframe của 6 Extension (`all_frames: true`).
  - [`hook_main.js`](./Argon_Collector/hook_main.js):
    - Ép mở khóa mọi `ShadowRoot` (`closed` $\rightarrow$ `open`) để đọc DOM và bấm nút của cả 6 Extension.
    - Chặn các gói telemetry (`sentry`, `mixpanel`, `amplitude`, `segment`, `/statistics/*`).
    - Móc vào `window.fetch` và `XMLHttpRequest` để bắt trọn dữ liệu JSON trả về: tự động tách **Email Công Ty (`workEmails`)** vs **Email Cá Nhân (`personalEmails`)**, lọc **SĐT (`phones`)** và đọc số dư Credit thực tế.
  - [`hook_bridge.js`](./Argon_Collector/hook_bridge.js) & [`background.js`](./Argon_Collector/background.js): Cầu nối liên lạc giữa các iframe với `http://127.0.0.1:8765`.
  - [`linkedin_orchestrator.js`](./Argon_Collector/linkedin_orchestrator.js): Bộ điều phối trên trang `linkedin.com/in/*` kèm bảng **HUD nổi góc dưới bên trái**.
- [`accounts_config.json`](./accounts_config.json): Lưu cấu hình định danh của 20 Profile (`acc_1` $\rightarrow$ `acc_20`, `adspowerId`, `gmail`, `priority`, `enabled`). **Tuyệt đối không lưu cứng số dư Credit tĩnh** — toàn bộ số dư Credit được đọc động 100% theo thời gian thực từ 3 kênh:
  1. **API Network Interception (`hook_main.js`)**: Đọc trực tiếp các trường `credit`, `credits`, `remaining`, `balance`, `quota_left`, `{ used, limit }` trong JSON trả về của cả 6 Extension.
  2. **Live DOM / Shadow DOM Badge Scanner (`scanDomCreditsForSource`)**: Quét trực tiếp con số hiển thị trên badge/header của từng Extension (ví dụ `"38/50 credits"`, `"42 credits left"`, `"Out of credits"`) mỗi 3.5 giây và sau mỗi lần bấm.
  3. **LevelDB / Extension Local Storage (`read_leveldb_account_info`)**: Đọc dữ liệu thực tế lưu trong ổ đĩa của Profile.
  - **Không bao giờ tự ý lấy số cố định trừ lùi (`-1`, `-8`) trong Python** vì có những hồ sơ không tìm thấy thông tin thì Extension không trừ credit hoặc chu kỳ hồi của từng tài khoản khác nhau.
- [`urls.txt`](./urls.txt): Danh sách các link hồ sơ LinkedIn cần quét.
- [`ket_qua.json`](./ket_qua.json) & [`ket_qua.csv`](./ket_qua.csv): Kết quả đầu ra đã gộp đa nguồn.

---

### B. Chiến thuật điều phối trên mỗi Hồ sơ LinkedIn (`liUrl`)

1. **Luồng Email — "Đánh Hội Đồng & Gộp Đa Nguồn"**:
   - Kích hoạt tìm Email trên **cả 5 Extension tự động** (`ContactOut`, `Kendo`, `Snov.io`, `Apollo [chế độ 1 credit Email]`, `Lusha`).
   - Lý do: Nếu thằng này có **Email công ty** (`@tencongty.com`) còn thằng kia có **Email cá nhân** (`@gmail.com`), Server sẽ **gộp (union) và lọc trùng** tất cả lại vào chung hồ sơ ứng viên đó.

2. **Luồng Số Điện Thoại (SĐT) — "Thác Nước 4 Tầng" (Waterfall tiết kiệm Credit)**:
   - **Tầng 1 (`ContactOut`)**: Tìm SĐT bằng ContactOut trước tiên (vì 5 lượt/ngày tự hồi).
     - Nếu **có SĐT** $\rightarrow$ **Dừng luồng SĐT ngay**, khóa nút SĐT của Lusha và Apollo (tiết kiệm credit tháng).
   - **Tầng 2 (`Lusha`)**: Chỉ tự động bấm tìm SĐT trên Lusha khi `ContactOut` **không ra SĐT**.
     - Nếu Lusha **có SĐT** $\rightarrow$ **Dừng luồng SĐT**, khóa nút SĐT của Apollo.
   - **Tầng 3 (`Apollo - 8 credit`)**: Chỉ cho phép Apollo bấm lấy SĐT khi **cả ContactOut lẫn Lusha đều bó tay (`0 SĐT`)**.
   - **Tầng 4 (`SignalHire - Phương án B: Bấm tay cuối buổi`)**:
     - Nếu chạy qua cả 3 tầng tự động (`ContactOut` $\rightarrow$ `Lusha` $\rightarrow$ `Apollo`) mà ứng viên vẫn trắng SĐT (`phones: []`), hệ thống **KHÔNG dừng máy** mà tự động gắn cờ `needSignalHire: true`, đưa ứng viên đó vào tab **`🎯 Cứu Nét SignalHire`** trên Dashboard và chuyển sang URL tiếp theo.
     - Cuối buổi, người dùng mở tab **`🎯 Cứu Nét SignalHire`**, bấm nút **`🎯 Mở Profile còn SignalHire để bấm`** $\rightarrow$ tự tay bấm nút Reveal của SignalHire (hoặc bấm nút vàng trên thanh HUD) $\rightarrow$ kết quả tự động hứng về và gộp khít vào `ket_qua.json` & `ket_qua.csv`.

3. **Nhịp xoay vòng 20 Profile (Cách 1 — 5 URL / lần mở Profile) & Bù khuyết động**:
   - Mỗi Profile khi mở lên sẽ chạy **5 URL** (vừa khít 5 lượt/ngày của ContactOut), nghỉ ngẫu nhiên `20–35s` giữa các URL.
   - Xong 5 URL $\rightarrow$ đóng Profile hiện tại, nghỉ `25–40s`, rồi mở Profile kế tiếp. Với 50 link/ngày, mỗi ngày chỉ dùng đúng 10 Profile.
   - **Điều phối bù khuyết (`missingSources`)**: Nếu trên một URL có 1 extension báo hết credit sớm (`outOfCredits`), URL đó được ghi nhận `missingSources` để khi mở sang Profile kế tiếp, `/task_plan` chỉ bật đúng cái extension bị thiếu đó lên chạy bù rồi gộp vào kết quả cũ mà không làm tốn lại credit của các extension đã lấy xong.

---

## 3. Hướng dẫn cho Argon trên máy mới: Cần làm gì tiếp theo?

Khi bạn (Argon trên máy mới) đọc được file này sau khi `git clone https://github.com/thbn12082/HR-Tools.git`, hãy thực hiện theo đúng thứ tự sau:

1. **Giữ nguyên các nguyên tắc đã chốt với Chủ nhân**:
   - **Đọc Credit Động 100%**: Tuyệt đối không gán cứng số credit ban đầu rồi trừ lùi thủ công (`-1`, `-8`). Mọi con số credit phải được đọc động từ API trả về, từ DOM giao diện của Extension hoặc từ LevelDB.
   - Không viết lại code spoof fingerprint trong extension (AdsPower đã lo).
   - Không đổi sang chạy đa luồng/song song nhiều trình duyệt cùng lúc (vì đang dùng mạng công ty 1 IP).
   - Tuyệt đối không cho `SignalHire` tự động bấm trong mọi trường hợp.

2. **Kết nối với phần mềm AdsPower trên máy mới**:
   - Đảm bảo ứng dụng **AdsPower** đang mở và bật **Local API** ở cổng mặc định `http://127.0.0.1:50325`.
   - Chạy server bằng lệnh:
     ```powershell
     python argon_server.py
     ```
   - Mở trình duyệt vào `http://127.0.0.1:8765`, bấm nút **`🔄 Đồng bộ từ AdsPower API (50325)`** trên tab đầu tiên để hút tự động danh sách 20 `user_id` từ AdsPower trên máy mới vào `accounts_config.json` (hoặc điền `user_id` của AdsPower vào từng thẻ Profile).

3. **Nạp `Argon_Collector` vào 20 Profile AdsPower**:
   - Trên AdsPower, 6 extension gốc (`ContactOut`, `Kendo`, `Apollo`, `Snov.io`, `Lusha`, `SignalHire`) cài từ Chrome Web Store.
   - Khi `argon_server.py` gọi AdsPower API `/api/v1/browser/start`, nó đã tự động truyền `--load-extension=<đường_dẫn>/Argon_Collector`. Nếu người dùng mở thủ công từ giao diện AdsPower, có thể thêm thư mục `Argon_Collector` vào mục *Extensions* của AdsPower để đồng bộ cho cả 20 Profile.

4. **Việc kỹ thuật cần hỗ trợ tinh chỉnh khi chạy thực tế trên máy mới**:
   - Nếu có bất kỳ extension nào trong 4 thằng mới (`Kendo`, `Snov.io`, `Lusha`, `SignalHire`) cập nhật giao diện UI trên Chrome Web Store khiến nút bấm thay đổi selector hoặc cấu trúc JSON API trả về khác đi, hãy kiểm tra DOM/Network thực tế trên máy đó và cập nhật bổ sung vào 2 hàm `executeServiceAction()` và `walkJsonPayload()` trong [`Argon_Collector/hook_main.js`](./Argon_Collector/hook_main.js).
