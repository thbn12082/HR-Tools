# argon_server.py — Máy chủ Điều Phối Động 6 Extension (ContactOut, Kendo, Apollo, Snov.io, Lusha, SignalHire)
# Quản lý Sổ Cái Credit 20 Profile AdsPower • Chạy tuần tự 5 URL/Ca • Gộp Mail Công Ty + Mail Cá Nhân + Thác Nước SĐT
# Chạy bằng lệnh: python C:\Users\nguyen_khac_thu\Desktop\Argon\argon_server.py

import concurrent.futures
import csv
import hashlib
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = "127.0.0.1"
PORT = 8765

BASE_DIR = pathlib.Path(__file__).parent.resolve()
ARGON_COLLECTOR_DIR = BASE_DIR / "Argon_Collector"
PROFILES_DIR = BASE_DIR / "profiles"
URLS_FILE = BASE_DIR / "urls.txt"
JSON_OUT = BASE_DIR / "ket_qua.json"
CSV_OUT = BASE_DIR / "ket_qua.csv"
ACCOUNTS_CONFIG_FILE = BASE_DIR / "accounts_config.json"

ADSPOWER_API_BASE = "http://127.0.0.1:50325"
URLS_PER_PROFILE_SESSION = 5

DEFAULT_SERVICE_CREDITS = {
    "contactout": 5,   # 5 lượt/ngày (tự hồi mỗi ngày)
    "kendo": 50,       # 50 credit/tháng (1 cr/email)
    "apollo": 80,      # 80 credit/tháng (1 cr/email, 8 cr/sđt)
    "snov": 50,        # 50 credit/tháng
    "lusha": 40,       # 40 credit/tháng
    "signalhire": 10,  # 10 credit/tháng (chỉ bấm tay cứu nét)
}

CONTACTOUT_EXT_ID = "jjdemeiffadmmjhkbbpglgnlgeafomjo"
APOLLO_EXT_ID = "alhgpfoeiimagjlnfekdhkjlkiomcapa"

DEFAULT_MAX_EMAIL_QUOTA = 5
DEFAULT_MAX_PHONE_QUOTA = 5
MIN_DELAY_BETWEEN_URLS = 20
MAX_DELAY_BETWEEN_URLS = 35
MIN_DELAY_BETWEEN_ACCS = 25
MAX_DELAY_BETWEEN_ACCS = 40
TASK_TIMEOUT_SEC = 95


def safe_write_json(
    file_path: pathlib.Path,
    data: list | dict,
    max_retries: int = 3,
    retry_delay: float = 0.5,
) -> pathlib.Path:
    """Ghi file JSON an toàn trên Windows chống lỗi file lock (Excel/Editor) bằng cơ chế retry và backup."""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    last_err = None
    for attempt in range(max_retries):
        try:
            file_path.write_text(content, encoding="utf-8")
            return file_path
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    # Nếu sau các lần thử vẫn bị khóa (do Excel/Editor giữ exclusive lock)
    ts = int(time.time())
    backup_path = file_path.with_name(f"{file_path.stem}_backup_{ts}{file_path.suffix}")
    try:
        backup_path.write_text(content, encoding="utf-8")
        msg = f"[!] CẢNH BÁO: File {file_path.name} đang bị khóa ({last_err}). Đã tự động lưu dự phòng vào: {backup_path.name}"
        if "STATE" in globals() and hasattr(globals()["STATE"], "add_log"):
            globals()["STATE"].add_log(msg)
        else:
            print(msg)
        return backup_path
    except Exception:
        session_path = file_path.with_name(f"{file_path.stem}_session{file_path.suffix}")
        try:
            session_path.write_text(content, encoding="utf-8")
            return session_path
        except Exception:
            pass
    return file_path


def safe_write_csv(
    file_path: pathlib.Path,
    rows: list[list[str]],
    headers: list[str],
    max_retries: int = 3,
    retry_delay: float = 0.5,
) -> pathlib.Path:
    """Ghi file CSV an toàn trên Windows chống lỗi Excel exclusive lock bằng cơ chế retry và backup."""
    last_err = None
    for attempt in range(max_retries):
        try:
            with file_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            return file_path
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    # Nếu vẫn bị khóa sau 3 lần retry: ghi file backup kèm timestamp để bảo toàn dữ liệu
    ts = int(time.time())
    backup_path = file_path.with_name(f"{file_path.stem}_backup_{ts}{file_path.suffix}")
    try:
        with backup_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        msg = f"[!] CẢNH BÁO: File {file_path.name} đang bị khóa ({last_err}). Đã tự động lưu dự phòng vào: {backup_path.name}"
        if "STATE" in globals() and hasattr(globals()["STATE"], "add_log"):
            globals()["STATE"].add_log(msg)
        else:
            print(msg)
        return backup_path
    except Exception:
        session_path = file_path.with_name(f"{file_path.stem}_session{file_path.suffix}")
        try:
            with session_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            return session_path
        except Exception:
            pass
    return file_path


def find_chrome_exe() -> str:
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError("Không tìm thấy chrome.exe trên máy tính!")


def canonical_linkedin_slug(url_or_slug: str) -> str:
    """Trích xuất slug định danh duy nhất của hồ sơ LinkedIn để chống trùng lặp tuyệt đối."""
    if not url_or_slug:
        return ""
    u = str(url_or_slug).strip().split("?")[0].split("#")[0].strip("/")
    m = re.search(r'(?:linkedin\.com)?/in/([a-zA-Z0-9\-_%]+)', u, re.IGNORECASE)
    if m:
        slug = m.group(1).split("/")[0]
        return urllib.parse.unquote(slug).strip("-").lower()
    m_pub = re.search(r'(?:linkedin\.com)?/pub/([a-zA-Z0-9\-_%]+)', u, re.IGNORECASE)
    if m_pub:
        slug = m_pub.group(1).split("/")[0]
        return urllib.parse.unquote(slug).strip("-").lower()
    parts = [p for p in u.split("/") if p]
    if parts:
        for p in reversed(parts):
            p_clean = urllib.parse.unquote(p).strip("-").lower()
            if p_clean not in (
                "in", "pub", "recent-activity", "all", "overlay",
                "contact-info", "edit", "detail", "www.linkedin.com", "linkedin.com"
            ):
                return p_clean
    return ""


def infer_name_from_slug(slug: str) -> str:
    """Tự động suy luận họ tên chuẩn từ LinkedIn slug khi DOM chưa kịp load tên (ví dụ: haerang-yoo-20298038a -> Haerang Yoo)."""
    if not slug:
        return ""
    cleaned = re.sub(r'-[0-9a-fA-F]{6,}$', '', slug)
    cleaned = re.sub(r'-[0-9a-zA-Z]{8,}$', '', cleaned)
    cleaned = re.sub(r'-\d+$', '', cleaned)
    parts = [p for p in cleaned.split("-") if p]
    if not parts:
        return ""
    name_parts = []
    for p in parts:
        if len(p) == 1:
            name_parts.append(p.upper() + ".")
        else:
            name_parts.append(p.capitalize())
    return " ".join(name_parts).strip()


def normalize_url(url: str) -> str:
    """Chuẩn hóa URL LinkedIn về dạng canonical duy nhất https://www.linkedin.com/in/{slug}/"""
    slug = canonical_linkedin_slug(url)
    if slug:
        return f"https://www.linkedin.com/in/{slug}/"
    return url.strip().split("?")[0].rstrip("/").lower()


def read_leveldb_account_info(acc_id: str) -> dict:
    """Đọc ĐỘNG toàn bộ thông tin tài khoản & số lượt Email/SĐT trực tiếp từ dữ liệu ContactOut & Apollo trong Profile Chrome."""
    info = {
        "extensionId": "",
        "userId": None,
        "holderName": "",
        "accountEmail": "",
        "emailCredit": None,
        "phoneCredit": None,
        "plan": "",
        "atsExportLimit": None,
        "extInstalled": False,
        "apolloInstalled": False,
        "apolloEmail": "",
        "apolloUserId": "",
    }
    profile_dir = PROFILES_DIR / acc_id
    ext_storage_dir = profile_dir / "Default" / "Local Extension Settings" / CONTACTOUT_EXT_ID
    apollo_storage_dir = profile_dir / "Default" / "Local Extension Settings" / APOLLO_EXT_ID

    def _safe_sort_key(p: pathlib.Path) -> tuple[int, float]:
        try:
            if not p.is_file():
                return (0, 0.0)
            # .log (WAL) chứa dữ liệu mới nhất chưa nén xuống .ldb nên luôn đọc sau .ldb
            is_wal = 1 if p.suffix.lower() == ".log" else 0
            return (is_wal, p.stat().st_mtime)
        except OSError:
            return (0, 0.0)

    if ext_storage_dir.exists():
        try:
            files = sorted(ext_storage_dir.glob("*"), key=_safe_sort_key)
        except OSError:
            files = []

        for fpath in files:
            try:
                if (
                    not fpath.is_file()
                    or fpath.name in ("LOCK", "LOG", "LOG.old", "CURRENT")
                    or fpath.name.startswith("MANIFEST")
                ):
                    continue
                raw = fpath.read_bytes().decode("utf-8", errors="ignore")
                if raw:
                    info["extInstalled"] = True
                ext_ids = re.findall(r'CO__extension-id[^"a-f0-9]*"([a-f0-9-]{20,})"', raw)
                if ext_ids:
                    info["extensionId"] = ext_ids[-1]

                # Trích xuất chính xác từ khối JSON "user" của ContactOut
                for m in re.finditer(
                    r'"credit"\s*:\s*(\d+|null)\s*,\s*"domain"\s*:\s*"[^"]*"\s*,\s*"email"\s*:\s*"([^"]+)"',
                    raw,
                ):
                    c_val, em_val = m.group(1), m.group(2)
                    if c_val.isdigit():
                        info["emailCredit"] = int(c_val)
                    if em_val:
                        info["accountEmail"] = em_val

                    head = raw[max(0, m.start() - 4500) : m.start()]
                    ats_m = re.findall(r'"atsExportLimit"\s*:\s*(\d+)', head)
                    if ats_m:
                        info["atsExportLimit"] = int(ats_m[-1])

                    tail = raw[m.end() : m.end() + 4500]
                    nm = re.search(r'"name"\s*:\s*"([^"]+)"', tail)
                    if nm:
                        info["holderName"] = nm.group(1)

                    pc = re.search(r'"phoneCredit"\s*:\s*(\d+|null)', tail)
                    if pc and pc.group(1).isdigit():
                        info["phoneCredit"] = int(pc.group(1))

                    pr = re.search(r'"premium"\s*:\s*"([^"]+)"', tail)
                    if pr:
                        info["plan"] = pr.group(1)

                    uid = re.search(r'"userId"\s*:\s*(\d+)', tail)
                    if uid:
                        info["userId"] = int(uid.group(1))
            except Exception:
                pass

    # Đọc trạng thái đăng nhập Apollo Extension từ LevelDB của profile
    if apollo_storage_dir.exists():
        try:
            ap_files = sorted(apollo_storage_dir.glob("*"), key=_safe_sort_key)
        except OSError:
            ap_files = []
        for fpath in ap_files:
            try:
                if (
                    not fpath.is_file()
                    or fpath.name in ("LOCK", "LOG", "LOG.old", "CURRENT")
                    or fpath.name.startswith("MANIFEST")
                ):
                    continue
                raw_ap = fpath.read_bytes().decode("utf-8", errors="ignore")
                if not raw_ap:
                    continue
                ap_uids = re.findall(r'"currentUserId"\s*:\s*"([a-f0-9]{16,32})"', raw_ap)
                if ap_uids:
                    info["apolloUserId"] = ap_uids[-1]
                    info["apolloInstalled"] = True
                ap_emails = re.findall(r'\\"email\\"\s*:\s*\\"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\\"', raw_ap)
                if not ap_emails:
                    ap_emails = re.findall(r'"email"\s*:\s*"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"', raw_ap)
                if ap_emails:
                    info["apolloEmail"] = ap_emails[-1]
                    info["apolloInstalled"] = True
            except Exception:
                pass

    # Fallback đọc tên & email tài khoản Chrome từ Default/Preferences nếu chưa mở extension ContactOut
    if not info["accountEmail"] or not info["holderName"]:
        pref_file = profile_dir / "Default" / "Preferences"
        if pref_file.exists():
            try:
                pref_data = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
                acc_list = pref_data.get("account_info") or []
                if acc_list and isinstance(acc_list, list):
                    first_acc = acc_list[0] or {}
                    if not info["accountEmail"] and first_acc.get("email"):
                        info["accountEmail"] = first_acc["email"]
                    if not info["holderName"] and first_acc.get("full_name"):
                        info["holderName"] = first_acc["full_name"]
            except Exception:
                pass

    return info


def fetch_live_contactout_api_for_profile(acc_id: str, proxy: str = "") -> dict | None:
    """Đã vô hiệu hóa việc gửi request HTTP Python ngầm lên máy chủ ContactOut
    nhằm triệt tiêu hoàn toàn nguy cơ lệch TLS fingerprint (JA3/JA4) gây phát hiện/khóa tài khoản.
    Toàn bộ dữ liệu tài khoản và số lượt emailCredit, phoneCredit được đọc an toàn 100%
    trực tiếp từ LevelDB local của profile trên ổ đĩa (0% network traffic)."""
    try:
        info = read_leveldb_account_info(acc_id)
        if info.get("extInstalled") or info.get("accountEmail") or info.get("emailCredit") is not None:
            return info
    except Exception:
        pass
    return None


def kill_chrome_for_profile(proc: subprocess.Popen | None, profile_dir: pathlib.Path) -> None:
    # 1. Diệt cây tiến trình qua handle proc nếu có (không phụ thuộc vào proc.poll() để tránh sót process con)
    if proc is not None:
        try:
            pid = getattr(proc, "pid", None)
            if pid:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
        except Exception:
            pass

    # 2. Quét sạch tất cả tiến trình chrome.exe con (renderer, utility, crashpad, GPU)
    # gắn với profile_dir. Dùng biến môi trường truyền đường dẫn để miễn nhiễm hoàn toàn
    # với lỗi cú pháp PowerShell khi đường dẫn chứa khoảng trắng, dấu ngoặc vuông `[]`, ký tự tiếng Việt.
    try:
        resolved_prof = str(profile_dir.resolve())
        env = os.environ.copy()
        env["CHROME_TARGET_PROFILE"] = resolved_prof
        ps_script = (
            "$target = $env:CHROME_TARGET_PROFILE\n"
            "if ($target) {\n"
            "    $procs = @()\n"
            "    try {\n"
            "        $procs = Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" -ErrorAction Stop\n"
            "    } catch {\n"
            "        try { $procs = Get-WmiObject Win32_Process -Filter \"Name = 'chrome.exe'\" -ErrorAction SilentlyContinue } catch {}\n"
            "    }\n"
            "    foreach ($p in $procs) {\n"
            "        if ($p.CommandLine -and ($p.CommandLine.IndexOf($target, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)) {\n"
            "            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}\n"
            "            & taskkill.exe /F /T /PID $p.ProcessId 2>$null\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except Exception:
        pass
    time.sleep(0.2)


def fetch_adspower_user_list() -> list[dict]:
    """Lấy danh sách các Profile từ AdsPower Local API (http://127.0.0.1:50325/api/v1/user/list)."""
    try:
        req = urllib.request.Request(
            f"{ADSPOWER_API_BASE}/api/v1/user/list?page=1&page_size=100",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("code") == 0 and isinstance(data.get("data", {}).get("list"), list):
                return data["data"]["list"]
    except Exception:
        pass
    return []


def start_adspower_profile(adspower_id: str, start_urls: list[str] | None = None) -> bool:
    """Mở trình duyệt AdsPower theo user_id và nạp Argon_Collector."""
    if not adspower_id:
        return False
    try:
        ext_paths = [str(ARGON_COLLECTOR_DIR.resolve())]
        launch_args = [f"--load-extension={','.join(ext_paths)}"]
        if start_urls:
            launch_args.extend(start_urls)
        qs = urllib.parse.urlencode({
            "user_id": adspower_id,
            "open_tabs": "1",
            "launch_args": json.dumps(launch_args),
        })
        req = urllib.request.Request(f"{ADSPOWER_API_BASE}/api/v1/browser/start?{qs}")
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data.get("code") == 0
    except Exception:
        return False


def stop_adspower_profile(adspower_id: str) -> bool:
    """Đóng trình duyệt AdsPower theo user_id."""
    if not adspower_id:
        return False
    try:
        qs = urllib.parse.urlencode({"user_id": adspower_id})
        req = urllib.request.Request(f"{ADSPOWER_API_BASE}/api/v1/browser/stop?{qs}")
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data.get("code") == 0
    except Exception:
        return False


def is_adspower_profile_active(adspower_id: str) -> bool:
    """Kiểm tra trình duyệt AdsPower có đang mở hay không."""
    if not adspower_id:
        return False
    try:
        qs = urllib.parse.urlencode({"user_id": adspower_id})
        req = urllib.request.Request(f"{ADSPOWER_API_BASE}/api/v1/browser/active?{qs}")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data.get("code") == 0 and data.get("data", {}).get("status") == "Active"
    except Exception:
        return True


def launch_chrome_profile(
    acc: dict,
    start_urls: list[str],
    engine_mode: str = "multi",
) -> subprocess.Popen | None:
    adspower_id = (acc.get("adspowerId") or "").strip()
    if adspower_id:
        start_adspower_profile(adspower_id, start_urls)
        return None

    chrome_exe = find_chrome_exe()
    profile_dir = PROFILES_DIR / acc["id"]
    profile_dir.mkdir(parents=True, exist_ok=True)

    kill_chrome_for_profile(None, profile_dir)
    time.sleep(0.4)

    # Khử cờ báo crash trong Default/Preferences sau khi taskkill để Chrome không hiện popup "Restore pages?"
    pref_path = profile_dir / "Default" / "Preferences"
    if pref_path.exists():
        try:
            raw_pref = pref_path.read_text(encoding="utf-8", errors="ignore")
            patched_pref = re.sub(r'"exit_type"\s*:\s*"[^"]*"', '"exit_type":"Normal"', raw_pref)
            patched_pref = re.sub(r'"exited_cleanly"\s*:\s*false', '"exited_cleanly":true', patched_pref)
            if patched_pref != raw_pref:
                pref_path.write_text(patched_pref, encoding="utf-8")
        except Exception:
            pass

    acc_hash = hashlib.md5(str(acc["id"]).encode("utf-8")).digest()
    win_presets = [
        (1440, 860, 24, 18),
        (1380, 820, 48, 28),
        (1520, 880, 16, 14),
        (1400, 840, 36, 22),
        (1480, 850, 30, 20),
        (1366, 800, 42, 24),
    ]
    win_w, win_h, pos_x, pos_y = win_presets[acc_hash[0] % len(win_presets)]
    win_w += (acc_hash[1] % 5) * 4
    win_h += (acc_hash[2] % 5) * 4

    ext_dirs = [str(ARGON_COLLECTOR_DIR.resolve())]
    load_ext_arg = f"--load-extension={','.join(ext_dirs)}"

    args = [
        chrome_exe,
        f"--user-data-dir={profile_dir.resolve()}",
        "--profile-directory=Default",
        load_ext_arg,
        "--new-window",
        f"--window-size={win_w},{win_h}",
        f"--window-position={pos_x},{pos_y}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=OptimizationGuideModelDownloading,OptimizationHintsFetching,Translate,MediaRouter",
        "--lang=en-US,en",
        "--disable-session-crashed-bubble",
        "--enforce-webrtc-ip-permission-check",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    ]
    if acc.get("proxy"):
        args.append(f"--proxy-server={acc['proxy']}")

    cleaned_start_urls = []
    for u in start_urls:
        if "linkedin.com" in u.lower():
            cleaned_start_urls.append(normalize_url(u))
        else:
            cleaned_start_urls.append(u)
    args.extend(cleaned_start_urls)

    # Bắt buộc hiển thị cửa sổ thật (SW_SHOWNORMAL = 1) để không bị ẩn khi chạy từ tiến trình nền
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 1

    proc = subprocess.Popen(args, startupinfo=si)

    def _bring_to_front(pid: int) -> None:
        time.sleep(1.2)
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(New-Object -ComObject WScript.Shell).AppActivate({pid}) | Out-Null",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except Exception:
            pass

    threading.Thread(target=_bring_to_front, args=(proc.pid,), daemon=True).start()
    return proc



class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.user_prefs: dict[str, dict] = self._load_user_prefs()
        self.live_runtime: dict[str, dict] = {}
        self.accounts: list[dict] = []
        self.results: list[dict] = self._load_existing_results()
        self.logs: list[str] = []
        self.quota_mode: str = "standard"  # "standard" | "require_phone" | "require_email"

        # Trạng thái tiến trình chạy tự động (2 Pha: Pha 1 = Apollo Unlimited Email -> Pha 2 = ContactOut Fallback)
        self.current_phase: str = "multi"
        self.is_running: bool = False
        self.stop_requested: bool = False
        self.active_acc_id: str | None = None
        self.active_proc: subprocess.Popen | None = None
        self.manual_proc: subprocess.Popen | None = None
        self.manual_acc_id: str | None = None

        self.pending_urls: list[str] = []
        self.total_campaign_urls: int = 0
        self.acc_used_in_session: int = 0
        self.acc_exhausted: bool = False
        self.in_progress_url: str | None = None
        self.in_progress_since: float = 0.0
        self.next_allowed_time: float = 0.0
        self.force_refresh_credits: bool = False

        self.sync_all_accounts_from_disk()
        self.sync_all_accounts_from_contactout_api()
        self.reload_urls_from_file()
        self.add_log("Hệ thống Điều phối động 6 Extension và Sổ cái 20 Profile AdsPower đã sẵn sàng.")
        threading.Thread(target=self._periodic_api_sync_loop, daemon=True).start()

    def _periodic_api_sync_loop(self) -> None:
        while True:
            time.sleep(20)
            try:
                self.sync_all_accounts_from_contactout_api()
            except Exception:
                pass

    def sync_all_accounts_from_contactout_api(self) -> None:
        """Đồng bộ thông tin tài khoản & số lượt Email/SĐT từ LevelDB nội bộ của profile (an toàn tuyệt đối, 0% network traffic)."""
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        prof_dirs = [d for d in PROFILES_DIR.iterdir() if d.is_dir()]
        if not prof_dirs:
            return

        def _fetch_one(acc_id: str) -> tuple[str, dict | None]:
            pref = self.user_prefs.get(acc_id, {})
            return acc_id, fetch_live_contactout_api_for_profile(acc_id, pref.get("proxy", ""))

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(_fetch_one, d.name) for d in prof_dirs]
            results = [f.result() for f in futures]

        with self.lock:
            for acc_id, api_info in results:
                if api_info:
                    live = self.live_runtime.setdefault(acc_id, {})
                    if api_info.get("userId"):
                        live["userId"] = api_info["userId"]
                    if api_info.get("holderName"):
                        live["holderName"] = api_info["holderName"]
                    if api_info.get("accountEmail"):
                        live["accountEmail"] = api_info["accountEmail"]
                    if api_info.get("plan"):
                        live["plan"] = api_info["plan"]
                    # Chỉ ghi đè từ ổ cứng nếu tài khoản đó đang không mở chạy trực tiếp (tránh LevelDB cũ chưa flush ghi đè số lượt thực tế)
                    is_actively_open = (acc_id == self.active_acc_id or acc_id == self.manual_acc_id)
                    if isinstance(api_info.get("emailCredit"), int):
                        if not is_actively_open or not isinstance(live.get("emailCredit"), int):
                            live["emailCredit"] = api_info["emailCredit"]
                    if isinstance(api_info.get("phoneCredit"), int):
                        if not is_actively_open or not isinstance(live.get("phoneCredit"), int):
                            live["phoneCredit"] = api_info["phoneCredit"]
                    if isinstance(api_info.get("atsExportLimit"), int):
                        live["atsExportLimit"] = api_info["atsExportLimit"]
                    if api_info.get("extInstalled"):
                        live["extInstalled"] = True
                    if api_info.get("apolloInstalled"):
                        live["apolloInstalled"] = True
                    if api_info.get("apolloEmail"):
                        live["apolloEmail"] = api_info["apolloEmail"]
                    if api_info.get("apolloUserId"):
                        live["apolloUserId"] = api_info["apolloUserId"]
            self.sync_all_accounts_from_disk()

    def add_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        with self.lock:
            self.logs.append(line)
            if len(self.logs) > 250:
                self.logs.pop(0)

    def _load_user_prefs(self) -> dict[str, dict]:
        """Chỉ lưu cấu hình bật/tắt & proxy của từng thư mục profile, tuyệt đối không lưu cứng thông tin tài khoản hay số lượt."""
        if ACCOUNTS_CONFIG_FILE.exists():
            try:
                raw = json.loads(ACCOUNTS_CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
            except Exception:
                pass
        return {}

    def save_accounts(self) -> None:
        prefs = {}
        for acc in self.accounts:
            prefs[acc["id"]] = {
                "enabled": acc.get("enabled", True),
                "proxy": acc.get("proxy", ""),
                "priority": acc.get("priority", 99),
                "adspowerId": acc.get("adspowerId", ""),
                "gmail": acc.get("gmail", ""),
                "name": acc.get("customName") or acc.get("name") or "",
                "lastDailyReset": acc.get("lastDailyReset") or time.strftime("%Y-%m-%d"),
                "credits": acc.get("credits") or dict(DEFAULT_SERVICE_CREDITS),
            }
        self.user_prefs = prefs
        try:
            safe_write_json(ACCOUNTS_CONFIG_FILE, prefs)
        except Exception:
            pass

    def init_20_adspower_profiles(self) -> int:
        """Khởi tạo nhanh 20 Profile (acc_1 -> acc_20) với định mức chuẩn của 6 Extension."""
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            created_count = 0
            for i in range(1, 21):
                acc_id = f"acc_{i}"
                (PROFILES_DIR / acc_id).mkdir(parents=True, exist_ok=True)
                if acc_id not in self.user_prefs:
                    self.user_prefs[acc_id] = {
                        "enabled": True,
                        "proxy": "",
                        "priority": i,
                        "adspowerId": "",
                        "gmail": f"gmail_{i:02d}@gmail.com",
                        "name": f"AdsPower #{i:02d}",
                        "lastDailyReset": today,
                        "credits": dict(DEFAULT_SERVICE_CREDITS),
                    }
                    created_count += 1
            safe_write_json(ACCOUNTS_CONFIG_FILE, self.user_prefs)
            self.sync_all_accounts_from_disk()
            return created_count

    def sync_profiles_from_adspower_api(self) -> int:
        """Đồng bộ danh sách user_id trực tiếp từ AdsPower Local API (127.0.0.1:50325)."""
        ap_list = fetch_adspower_user_list()
        if not ap_list:
            return 0
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            synced = 0
            for idx, item in enumerate(ap_list[:20], start=1):
                uid = str(item.get("user_id") or "").strip()
                if not uid:
                    continue
                acc_id = f"acc_{idx}"
                (PROFILES_DIR / acc_id).mkdir(parents=True, exist_ok=True)
                pref = self.user_prefs.get(acc_id, {})
                pref["enabled"] = pref.get("enabled", True)
                pref["priority"] = pref.get("priority", idx)
                pref["adspowerId"] = uid
                pref["name"] = item.get("name") or pref.get("name") or f"AdsPower #{idx:02d}"
                if item.get("remark") and "@" in str(item.get("remark")):
                    pref["gmail"] = str(item.get("remark")).strip()
                pref["lastDailyReset"] = pref.get("lastDailyReset") or today
                if "credits" not in pref or not isinstance(pref["credits"], dict):
                    pref["credits"] = dict(DEFAULT_SERVICE_CREDITS)
                self.user_prefs[acc_id] = pref
                synced += 1
            safe_write_json(ACCOUNTS_CONFIG_FILE, self.user_prefs)
            self.sync_all_accounts_from_disk()
            return synced

    def sync_all_accounts_from_disk(self) -> None:
        """Quét động toàn bộ các thư mục trong profiles/ + user_prefs và đồng bộ sổ cái 6 Extension."""
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        for acc_id in list(self.user_prefs.keys()):
            (PROFILES_DIR / acc_id).mkdir(parents=True, exist_ok=True)

        prof_dirs = sorted(
            [d for d in PROFILES_DIR.iterdir() if d.is_dir()],
            key=lambda p: (
                int(re.search(r"\d+", p.name).group(0)) if re.search(r"\d+", p.name) else 999,
                p.name,
            ),
        )

        today = time.strftime("%Y-%m-%d")
        new_accounts: list[dict] = []
        prefs_modified = False

        for idx, pdir in enumerate(prof_dirs, start=1):
            acc_id = pdir.name
            disk_info = read_leveldb_account_info(acc_id)
            live = self.live_runtime.get(acc_id, {})
            pref = self.user_prefs.get(acc_id, {})

            if (
                not disk_info["extInstalled"]
                and not disk_info["accountEmail"]
                and not disk_info["holderName"]
                and acc_id not in self.user_prefs
                and idx > 3
            ):
                continue

            raw_credits = pref.get("credits")
            if not isinstance(raw_credits, dict):
                raw_credits = dict(DEFAULT_SERVICE_CREDITS)
                prefs_modified = True
            else:
                for k, def_v in DEFAULT_SERVICE_CREDITS.items():
                    if k not in raw_credits or not isinstance(raw_credits[k], (int, float)):
                        raw_credits[k] = def_v
                        prefs_modified = True

            # Tự động hồi 5 lượt/ngày cho ContactOut khi sang ngày mới
            last_reset = pref.get("lastDailyReset") or ""
            if last_reset != today:
                raw_credits["contactout"] = DEFAULT_SERVICE_CREDITS["contactout"]
                pref["lastDailyReset"] = today
                pref["credits"] = raw_credits
                self.user_prefs[acc_id] = pref
                prefs_modified = True

            # Đồng bộ số dư thực tế nếu live_runtime báo về
            live_credits = live.get("credits") or {}
            for k, val in live_credits.items():
                if isinstance(val, int) and val >= 0:
                    raw_credits[k] = val

            email_credit = (
                live["emailCredit"]
                if isinstance(live.get("emailCredit"), int)
                else (
                    disk_info.get("emailCredit")
                    if isinstance(disk_info.get("emailCredit"), int)
                    else raw_credits.get("contactout", 5)
                )
            )
            raw_credits["contactout"] = email_credit

            phone_credit = (
                live["phoneCredit"]
                if isinstance(live.get("phoneCredit"), int)
                else (
                    disk_info.get("phoneCredit")
                    if isinstance(disk_info.get("phoneCredit"), int)
                    else raw_credits.get("contactout", 5)
                )
            )
            holder_name = live.get("holderName") or disk_info["holderName"] or pref.get("name") or ""
            account_email = (
                live.get("accountEmail")
                or disk_info["accountEmail"]
                or pref.get("gmail")
                or ""
            )
            plan = live.get("plan") or disk_info["plan"] or ""
            base_max = live.get("atsExportLimit") or disk_info["atsExportLimit"] or DEFAULT_MAX_EMAIL_QUOTA

            max_email = max(base_max, email_credit if isinstance(email_credit, int) else base_max)
            max_phone = max(base_max, phone_credit if isinstance(phone_credit, int) else base_max)

            display_name = pref.get("name") or (holder_name if holder_name else f"Profile {acc_id}")
            apollo_installed = bool(disk_info.get("apolloInstalled") or live.get("apolloInstalled"))
            apollo_email = live.get("apolloEmail") or disk_info.get("apolloEmail") or account_email
            apollo_uid = live.get("apolloUserId") or disk_info.get("apolloUserId") or ""

            new_accounts.append({
                "id": acc_id,
                "name": display_name,
                "customName": pref.get("name", ""),
                "adspowerId": pref.get("adspowerId", ""),
                "gmail": account_email,
                "proxy": pref.get("proxy", ""),
                "enabled": pref.get("enabled", True),
                "priority": pref.get("priority", idx),
                "lastDailyReset": pref.get("lastDailyReset", today),
                "credits": dict(raw_credits),
                "extInstalled": bool(disk_info["extInstalled"] or live.get("extInstalled") or pref.get("adspowerId")),
                "extensionId": disk_info["extensionId"] or live.get("extensionId") or "",
                "userId": disk_info["userId"] or live.get("userId"),
                "holderName": holder_name,
                "accountEmail": account_email,
                "plan": plan,
                "emailCredit": email_credit,
                "phoneCredit": phone_credit,
                "maxEmail": max_email,
                "maxPhone": max_phone,
                "apolloInstalled": apollo_installed,
                "apolloEmail": apollo_email,
                "apolloUserId": apollo_uid,
            })

        new_accounts.sort(key=lambda a: (a.get("priority", 99), a["id"]))
        self.accounts = new_accounts
        if prefs_modified:
            self.save_accounts()

    def get_task_plan(self, li_url: str) -> dict:
        """Trả về kế hoạch điều phối động (Task Plan) cho URL trên Profile đang chạy."""
        with self.lock:
            rec = self._find_record_for_url(li_url)
            checked = set((rec.get("checkedSources") or []) if rec else [])
            already_has_phone = bool(rec and len(rec.get("phones") or []) > 0)

            acc_id = self.active_acc_id or self.manual_acc_id
            acc = next((a for a in self.accounts if a["id"] == acc_id), None)
            if not acc and self.accounts:
                acc = self.accounts[0]

            credits = (acc.get("credits") if acc else None) or dict(DEFAULT_SERVICE_CREDITS)

            email_exts = []
            for svc in ["contactout", "kendo", "snov", "apollo", "lusha"]:
                if credits.get(svc, 0) > 0 and svc not in checked:
                    email_exts.append(svc)

            phone_waterfall = []
            if not already_has_phone:
                if credits.get("contactout", 0) > 0:
                    phone_waterfall.append("contactout")
                if credits.get("lusha", 0) > 0:
                    phone_waterfall.append("lusha")
                if credits.get("apollo", 0) >= 8:
                    phone_waterfall.append("apollo")

            return {
                "ok": True,
                "accId": acc["id"] if acc else "",
                "emailExtensions": email_exts,
                "phoneWaterfall": phone_waterfall,
                "alreadyHasPhone": already_has_phone,
                "credits": credits,
            }

    def _find_record_for_url(self, url_or_slug: str) -> dict | None:
        if not url_or_slug:
            return None
        slug = canonical_linkedin_slug(url_or_slug)
        norm_url = normalize_url(url_or_slug)
        for r in self.results:
            if r.get("outOfCredits"):
                continue
            r_url = r.get("liUrl") or ""
            r_slug = canonical_linkedin_slug(r_url)
            if slug and r_slug and slug == r_slug:
                return r
            if norm_url and r_url and normalize_url(r_url) == norm_url:
                return r
        return None

    def has_email_collected(self, url_or_slug: str) -> bool:
        """Kiểm tra ứng viên đã có ít nhất 1 Email hợp lệ chưa."""
        r = self._find_record_for_url(url_or_slug)
        if not r:
            return False
        emails = r.get("emails") or r.get("uiEmails") or r.get("secondaryEmails") or []
        return len(emails) > 0

    def is_already_collected(self, url_or_slug: str, phase: str | None = None) -> bool:
        """Kiểm tra xem hồ sơ này đã quét đủ các nguồn tự động chưa (hoặc có cần Profile khác bù nguồn bị hết credit không)."""
        if not url_or_slug:
            return False
        r = self._find_record_for_url(url_or_slug)
        if not r:
            return False

        missing = r.get("missingSources") or []
        if missing and self.active_acc_id:
            acc = next((a for a in self.accounts if a["id"] == self.active_acc_id), None)
            if acc:
                cr = acc.get("credits") or {}
                if any(cr.get(m, 0) > 0 for m in missing):
                    return False

        return bool(r.get("checkedSources") or r.get("coChecked") or r.get("apolloChecked") or r.get("emails") or r.get("phones"))

    def reclaim_in_progress_url(self, reason: str = "", fallback_url: str = "") -> str | None:
        """Thu hồi an toàn in_progress_url (hoặc fallback_url) về đầu danh sách pending_urls mà không bị trùng lặp."""
        with self.lock:
            url = self.in_progress_url or fallback_url
            if not url:
                return None

            clean_url = url.strip()
            self.in_progress_url = None
            self.in_progress_since = 0.0

            if not clean_url:
                return None

            if self.is_already_collected(clean_url, phase=self.current_phase):
                if reason:
                    self.add_log(f"[*] Thu hồi URL nhưng hồ sơ đã hoàn tất: {clean_url}")
                return clean_url

            cand_slug = canonical_linkedin_slug(clean_url)
            cand_norm = normalize_url(clean_url)
            already_in_pending = False
            for p in self.pending_urls:
                if p == clean_url:
                    already_in_pending = True
                    break
                if cand_slug and canonical_linkedin_slug(p) == cand_slug:
                    already_in_pending = True
                    break
                if cand_norm and normalize_url(p) == cand_norm:
                    already_in_pending = True
                    break

            if not already_in_pending:
                self.pending_urls.insert(0, clean_url)
                log_msg = f"[+] Đã thu hồi link an toàn về đầu hàng đợi: {clean_url}"
                if reason:
                    log_msg += f" ({reason})"
                self.add_log(log_msg)
            else:
                if reason:
                    self.add_log(f"[*] Link đã có trong hàng đợi: {clean_url} ({reason})")

            return clean_url

    def _clean_and_dedup_results(self, raw_list: list[dict]) -> list[dict]:
        """Tự động làm sạch, loại bỏ bản ghi rác và gộp trùng lặp tuyệt đối trên cơ sở dữ liệu kết quả."""
        if not raw_list:
            return []
        cleaned_list: list[dict] = []
        modified = False

        allowed_record_keys = {
            "timestamp", "accountId", "account", "fullName", "company", "headline",
            "emails", "phones", "uiEmails", "secondaryEmails", "uncertainEmails",
            "workEmails", "personalEmails", "checkedSources", "missingSources",
            "phoneSource", "needSignalHire",
            "github", "twitter", "openalex", "orcid", "liUrl",
            "apolloChecked", "coChecked", "source"
        }

        for item in raw_list:
            li_url = item.get("liUrl") or ""
            slug = canonical_linkedin_slug(li_url)
            fn = (item.get("fullName") or "").strip()

            # Xóa bỏ bản ghi Trần Hồ Khánh theo yêu cầu
            if "tran-ho-khanh" in li_url.lower() or "tran ho khanh" in fn.lower() or "trần hồ khánh" in fn.lower():
                modified = True
                continue

            # Tự động suy luận họ tên chuẩn nếu đang để trống hoặc "Chưa rõ tên"
            if not fn or fn.lower() in ("chưa rõ tên", "unknown", "linkedin member", "thành viên linkedin"):
                inferred = infer_name_from_slug(slug)
                if inferred:
                    fn = inferred
                    item["fullName"] = fn
                    modified = True

            # Loại bỏ các hàng rác thử nghiệm không có tên, không có liên hệ hoặc không phải link LinkedIn
            has_contacts = bool(item.get("emails") or item.get("phones") or item.get("coEmails") or item.get("coPhones"))
            is_real_linkedin = bool("linkedin.com" in li_url.lower())
            if not is_real_linkedin and not has_contacts:
                modified = True
                continue
            if not fn and not has_contacts and not slug:
                modified = True
                continue

            # Chuẩn hóa liUrl về link chuẩn nếu là LinkedIn URL
            if slug and "linkedin.com" in li_url.lower():
                canon_url = f"https://www.linkedin.com/in/{slug}/"
                if item.get("liUrl") != canon_url:
                    item["liUrl"] = canon_url
                    modified = True

            # Đồng bộ sang các trường liên lạc chuẩn nếu là dữ liệu cũ
            if not item.get("secondaryEmails") and item.get("socialEmails"):
                item["secondaryEmails"] = item["socialEmails"]
                modified = True
            if not item.get("phones") and (item.get("coPhones") or item.get("uiPhones")):
                item["phones"] = item.get("coPhones") or item.get("uiPhones") or []
                modified = True
            if not item.get("emails") and (item.get("coEmails") or item.get("uiEmails")):
                item["emails"] = item.get("coEmails") or item.get("uiEmails") or []
                modified = True

            # Lọc bỏ các trường rác không hiệu quả
            keys_to_remove = [k for k in item.keys() if k not in allowed_record_keys]
            if keys_to_remove:
                for k in keys_to_remove:
                    del item[k]
                modified = True

            # Kiểm tra xem người này đã tồn tại trong danh sách cleaned_list chưa
            matched_idx = None
            for idx, ex in enumerate(cleaned_list):
                ex_slug = canonical_linkedin_slug(ex.get("liUrl") or "")
                if slug and ex_slug:
                    if slug == ex_slug:
                        matched_idx = idx
                        break
                    # Nếu cả 2 đều có LinkedIn slug nhưng khác nhau -> là 2 hồ sơ khác nhau (kể cả trùng họ tên)
                    continue
                ex_name = (ex.get("fullName") or "").strip().lower()
                if fn and ex_name and fn.lower() == ex_name:
                    matched_idx = idx
                    break

            if matched_idx is not None:
                # Gộp dữ liệu an toàn, chỉ giữ các kênh liên lạc thực tế
                modified = True
                target = cleaned_list[matched_idx]
                for k in [
                    "emails", "phones", "uiEmails", "secondaryEmails", "uncertainEmails",
                    "github", "twitter"
                ]:
                    val_t = target.get(k) or []
                    val_i = item.get(k) or []
                    target[k] = list(dict.fromkeys(val_t + val_i))
                for k in ["fullName", "company", "headline", "openalex", "orcid"]:
                    if not target.get(k) and item.get(k):
                        target[k] = item[k]
                if item.get("apolloChecked"):
                    target["apolloChecked"] = True
                if item.get("coChecked"):
                    target["coChecked"] = True
            else:
                cleaned_list.append(item)

        if modified:
            try:
                safe_write_json(JSON_OUT, cleaned_list)
            except Exception:
                pass
        return cleaned_list

    def _load_existing_results(self) -> list[dict]:
        if JSON_OUT.exists():
            try:
                raw_list = json.loads(JSON_OUT.read_text(encoding="utf-8"))
                return self._clean_and_dedup_results(raw_list)
            except Exception:
                return []
        return []

    def get_raw_urls_text(self) -> str:
        if URLS_FILE.exists():
            return URLS_FILE.read_text(encoding="utf-8")
        return ""

    def save_raw_urls_text(self, text: str) -> None:
        for attempt in range(3):
            try:
                URLS_FILE.write_text(text.strip() + "\n", encoding="utf-8")
                break
            except (PermissionError, OSError):
                time.sleep(0.5)
        self.reload_urls_from_file()

    def reload_urls_from_file(self, phase: str | None = None) -> None:
        if not URLS_FILE.exists():
            self.pending_urls = []
            self.total_campaign_urls = 0
            return

        active_phase = (phase or self.current_phase or "apollo").lower()

        raw_lines = [
            line.strip()
            for line in URLS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.total_campaign_urls = len(raw_lines)

        filtered = []
        seen_in_batch = set()
        for u in raw_lines:
            slug = canonical_linkedin_slug(u)
            norm = normalize_url(u)
            key = slug if slug else norm
            if key in seen_in_batch:
                continue
            seen_in_batch.add(key)

            if self.is_already_collected(u, phase=active_phase):
                continue
            filtered.append(u)

        self.pending_urls = filtered

    def _match_account_for_payload(self, data: dict) -> dict | None:
        """Khớp chính xác tài khoản theo extensionId, userId hoặc accountEmail từ ContactOut / Apollo."""
        ext_id_in = (data.get("extensionId") or "").strip()
        user_id_in = data.get("userId")
        ap_uid_in = (data.get("apolloUserId") or "").strip()
        email_in = (data.get("accountEmail") or data.get("apolloEmail") or "").strip().lower()

        if ext_id_in:
            for a in self.accounts:
                if a.get("extensionId") == ext_id_in:
                    return a

        if ap_uid_in:
            for a in self.accounts:
                if a.get("apolloUserId") == ap_uid_in:
                    return a

        if isinstance(user_id_in, int) and user_id_in > 0:
            for a in self.accounts:
                if a.get("userId") == user_id_in:
                    return a

        if email_in:
            # Nếu đang mở 1 acc trùng email thì ưu tiên acc đang mở
            active_or_manual = self.active_acc_id or self.manual_acc_id
            if active_or_manual:
                for a in self.accounts:
                    if a["id"] == active_or_manual and (
                        (a.get("accountEmail") or "").strip().lower() == email_in
                        or (a.get("apolloEmail") or "").strip().lower() == email_in
                    ):
                        return a
            for a in self.accounts:
                if (
                    (a.get("accountEmail") or "").strip().lower() == email_in
                    or (a.get("apolloEmail") or "").strip().lower() == email_in
                ):
                    return a

        # Fallback về acc đang mở
        fallback_id = self.active_acc_id or self.manual_acc_id
        if fallback_id:
            for a in self.accounts:
                if a["id"] == fallback_id:
                    return a
        return None

    def update_live_account_status(self, data: dict) -> None:
        with self.lock:
            self.sync_all_accounts_from_disk()
            target_acc = self._match_account_for_payload(data)
            if not target_acc:
                return

            acc_id = target_acc["id"]
            live = self.live_runtime.setdefault(acc_id, {})
            live_credits = live.setdefault("credits", {})
            pref = self.user_prefs.setdefault(acc_id, {})
            pref_credits = pref.setdefault("credits", dict(DEFAULT_SERVICE_CREDITS))

            svc = (data.get("service") or data.get("engine") or "").strip().lower()
            if svc in DEFAULT_SERVICE_CREDITS:
                if data.get("outOfCredits"):
                    live_credits[svc] = 0
                    pref_credits[svc] = 0
                elif isinstance(data.get("emailCredit"), int):
                    live_credits[svc] = data["emailCredit"]
                    pref_credits[svc] = data["emailCredit"]
                if svc == "contactout" and isinstance(data.get("emailCredit"), int):
                    live["emailCredit"] = data["emailCredit"]
                if svc == "contactout" and isinstance(data.get("phoneCredit"), int):
                    live["phoneCredit"] = data["phoneCredit"]
                if data.get("accountEmail") and not pref.get("gmail"):
                    pref["gmail"] = data["accountEmail"]
                self.sync_all_accounts_from_disk()
                self.save_accounts()
                return

            if data.get("engine") == "apollo" or data.get("apolloInstalled"):
                live["apolloInstalled"] = True
                if data.get("apolloEmail") or data.get("accountEmail"):
                    live["apolloEmail"] = data.get("apolloEmail") or data.get("accountEmail")
                if data.get("apolloUserId"):
                    live["apolloUserId"] = str(data["apolloUserId"])
                if data.get("holderName") and not live.get("holderName"):
                    live["holderName"] = data["holderName"]
                self.sync_all_accounts_from_disk()
                return

            if data.get("extensionId"):
                live["extensionId"] = data["extensionId"]
            if isinstance(data.get("userId"), int) and data["userId"] > 0:
                live["userId"] = data["userId"]
            if data.get("holderName"):
                live["holderName"] = data["holderName"]
            if data.get("accountEmail"):
                live["accountEmail"] = data["accountEmail"]
            if data.get("plan"):
                live["plan"] = data["plan"]
            if isinstance(data.get("emailCredit"), int):
                live["emailCredit"] = data["emailCredit"]
                live_credits["contactout"] = data["emailCredit"]
                pref_credits["contactout"] = data["emailCredit"]
            if isinstance(data.get("phoneCredit"), int):
                live["phoneCredit"] = data["phoneCredit"]
            live["extInstalled"] = True

            self.sync_all_accounts_from_disk()
            self.save_accounts()

    def get_next_url_for_browser(self, requested_engine: str = "") -> dict:
        with self.lock:
            refresh_flag = self.force_refresh_credits
            self.force_refresh_credits = False

            if not self.is_running or self.stop_requested:
                return {"url": None, "refreshCredits": refresh_flag}

            now = time.time()
            if (
                self.acc_exhausted
                or self.in_progress_url is not None
                or not self.pending_urls
                or now < self.next_allowed_time
            ):
                return {"url": None, "refreshCredits": refresh_flag}

            target_url = None
            while self.pending_urls:
                cand = self.pending_urls.pop(0)
                if self.is_already_collected(cand, phase=self.current_phase):
                    self.add_log(f"[*] Ứng viên đã hoàn tất đủ nguồn -> Bỏ qua: {cand}")
                    continue
                target_url = cand
                break

            if not target_url:
                return {"url": None, "refreshCredits": refresh_flag}

            self.in_progress_url = target_url
            self.in_progress_since = now
            acc_label = self._get_acc_name(self.active_acc_id)
            self.add_log(
                f"[6-EXT | {acc_label}] Đang mở hồ sơ ({self.acc_used_in_session + 1}/{URLS_PER_PROFILE_SESSION} trong ca, còn {len(self.pending_urls)} link chờ): {target_url}"
            )
            return {"url": target_url, "refreshCredits": refresh_flag}

    def _get_acc_name(self, acc_id: str | None) -> str:
        for a in self.accounts:
            if a["id"] == acc_id:
                return f"{a['name']} ({a['id']})" if a.get("holderName") else a["name"]
        return acc_id or "Thủ công"

    def handle_result_from_browser(self, item: dict) -> None:
        source_engine = (item.get("source") or "multi").strip().lower()
        checked_sources = item.get("checkedSources") or [s.strip() for s in source_engine.split("+") if s.strip()]
        exhausted_sources = item.get("exhaustedSources") or []
        phone_source = (item.get("phoneSource") or "").strip().lower()
        is_apollo = (source_engine == "apollo")

        with self.lock:
            reported_li = (item.get("liUrl") or "").strip()
            in_prog = (self.in_progress_url or "").strip()

            if reported_li:
                target_li_url = reported_li
            elif in_prog:
                self.add_log(f"[!] Extension gửi kết quả nhưng thiếu liUrl! Từ chối gán vào {in_prog} để chống nhiễm chéo dữ liệu.")
                return
            else:
                self.add_log("[!] Bỏ qua kết quả không xác định được URL LinkedIn.")
                return

            target_slug = canonical_linkedin_slug(target_li_url)
            in_prog_slug = canonical_linkedin_slug(in_prog) if in_prog else ""

            matched = self._match_account_for_payload({"accountEmail": item.get("accountEmail")})
            acc_id = (
                self.active_acc_id
                or (matched["id"] if matched else None)
                or self.manual_acc_id
                or (self.accounts[0]["id"] if self.accounts else "acc_1")
            )

            live = self.live_runtime.setdefault(acc_id, {})
            live_credits = live.setdefault("credits", {})
            pref = self.user_prefs.setdefault(acc_id, {})
            pref_credits = pref.setdefault("credits", dict(DEFAULT_SERVICE_CREDITS))

            # Cập nhật sổ cái Credit của 6 Extension trên Profile hiện tại
            for ex_svc in exhausted_sources:
                if ex_svc in DEFAULT_SERVICE_CREDITS:
                    live_credits[ex_svc] = 0
                    pref_credits[ex_svc] = 0

            if source_engine == "signalhire":
                pref_credits["signalhire"] = max(0, int(pref_credits.get("signalhire", 10)) - 1)
                live_credits["signalhire"] = pref_credits["signalhire"]
                if not phone_source and (item.get("phones") or item.get("uiPhones")):
                    phone_source = "signalhire"
            else:
                for svc in checked_sources:
                    if svc not in DEFAULT_SERVICE_CREDITS:
                        continue
                    if svc in exhausted_sources:
                        continue
                    if svc == "apollo":
                        cost = 8 if phone_source == "apollo" else 1
                        pref_credits["apollo"] = max(0, int(pref_credits.get("apollo", 80)) - cost)
                        live_credits["apollo"] = pref_credits["apollo"]
                    elif svc == "contactout":
                        if isinstance(item.get("remainingCredit"), int):
                            pref_credits["contactout"] = item["remainingCredit"]
                        else:
                            pref_credits["contactout"] = max(0, int(pref_credits.get("contactout", 5)) - 1)
                        live_credits["contactout"] = pref_credits["contactout"]
                        live["emailCredit"] = pref_credits["contactout"]
                    else:
                        pref_credits[svc] = max(0, int(pref_credits.get(svc, DEFAULT_SERVICE_CREDITS[svc])) - 1)
                        live_credits[svc] = pref_credits[svc]

            self.sync_all_accounts_from_disk()
            self.save_accounts()

            acc_label = self._get_acc_name(acc_id)
            engine_tag = source_engine.upper()

            if item.get("outOfCredits") and len(checked_sources) <= 1 and not (item.get("emails") or item.get("phones")):
                self.add_log(f"[!] [{engine_tag} | {acc_label}] Báo hết lượt trên hồ sơ {target_li_url}! Chuyển sang Profile kế tiếp.")
                self.reclaim_in_progress_url(reason=f"{engine_tag} hết lượt", fallback_url=target_li_url)
                self.acc_exhausted = True
                return

            if in_prog and target_slug and in_prog_slug and target_slug != in_prog_slug:
                self.add_log(f"[*] Nhận kết quả {engine_tag} từ tab trước ({target_slug}) trong khi đang chờ {in_prog_slug}.")
            elif in_prog and source_engine != "signalhire":
                self.in_progress_url = None
                self.in_progress_since = 0.0

            ui_emails = list(dict.fromkeys(item.get("uiEmails") or []))
            uncertain_emails = list(dict.fromkeys(item.get("uncertainEmails") or []))
            work_emails = list(dict.fromkeys(item.get("workEmails") or []))
            personal_emails = list(dict.fromkeys(item.get("personalEmails") or []))
            ui_phones = list(dict.fromkeys(item.get("uiPhones") or []))
            uncertain_phones = list(dict.fromkeys(item.get("uncertainPhones") or []))

            if not ui_emails and not uncertain_emails and item.get("emails"):
                co_emails = list(dict.fromkeys(item.get("emails") or []))
                ui_emails = co_emails
            else:
                co_emails = list(dict.fromkeys(ui_emails + uncertain_emails))

            # Tự động phân loại Email Công ty vs Email Cá nhân nếu gói tin chưa tách sẵn
            personal_domains = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.com.vn", "hotmail.com", "outlook.com", "live.com", "icloud.com", "proton.me", "protonmail.com"}
            for em in co_emails:
                dom = em.split("@")[1].lower() if "@" in em else ""
                if dom in personal_domains:
                    if em not in personal_emails:
                        personal_emails.append(em)
                else:
                    if em not in work_emails:
                        work_emails.append(em)

            if not ui_phones and not uncertain_phones and item.get("phones"):
                co_phones = list(dict.fromkeys(item.get("phones") or []))
                ui_phones = co_phones
            else:
                co_phones = list(dict.fromkeys(ui_phones + uncertain_phones))

            slug = target_slug or canonical_linkedin_slug(target_li_url)
            fn = (item.get("fullName") or "").strip()
            if not fn or fn.lower() in ("chưa rõ tên", "unknown", "linkedin member", "thành viên linkedin"):
                inferred = infer_name_from_slug(slug)
                if inferred:
                    fn = inferred

            cp = (item.get("company") or "").strip()
            hl = item.get("headline") or ""

            if not fn and not co_emails and not co_phones and not slug:
                self.add_log(f"[!] Bỏ qua bản ghi rác không rõ tên và không có thông tin liên hệ: {target_li_url}")
                return

            if slug and "linkedin.com" in target_li_url.lower():
                target_li_url = f"https://www.linkedin.com/in/{slug}/"

            if source_engine != "signalhire":
                self.acc_used_in_session += 1
                delay = random.randint(MIN_DELAY_BETWEEN_URLS, MAX_DELAY_BETWEEN_URLS)
                self.next_allowed_time = time.time() + delay

                # Cách 1: Mỗi Profile chạy đúng nhịp 5 URL (hoặc khi ContactOut về 0 credit) thì chuyển sang Profile kế tiếp
                if self.acc_used_in_session >= URLS_PER_PROFILE_SESSION or pref_credits.get("contactout", 5) <= 0:
                    self.add_log(
                        f"[*] [{acc_label}] Đã hoàn thành nhịp {self.acc_used_in_session}/{URLS_PER_PROFILE_SESSION} link (ContactOut còn {pref_credits.get('contactout', 0)}/5) -> Chuyển sang Profile kế tiếp!"
                    )
                    self.acc_exhausted = True

                # Nếu có extension bị hết credit giữa chừng trên URL này -> đưa URL lại vào hàng đợi để Profile sau chạy bù đúng extension đó
                if exhausted_sources:
                    if target_li_url not in self.pending_urls:
                        self.pending_urls.insert(0, target_li_url)
                        self.add_log(
                            f"[*] URL {slug} có nguồn báo hết credit ({', '.join(exhausted_sources)}) -> Sẽ được Profile kế tiếp chạy bù tự động!"
                        )

        raw_gh = item.get("github") or []
        if isinstance(raw_gh, str):
            raw_gh = [raw_gh]
        raw_gh = [g for g in raw_gh if g]

        raw_tw = item.get("twitter") or []
        if isinstance(raw_tw, str):
            raw_tw = [raw_tw]
        raw_tw = [t for t in raw_tw if t]

        openalex_url = ""
        if item.get("openalex"):
            openalex_url = item.get("openalex") if isinstance(item["openalex"], str) else (item["openalex"].get("authorUrl") or "")
        orcid_url = item.get("orcid") or ""

        with self.lock:
            secondary_emails = [e for e in uncertain_emails if e not in ui_emails]
            all_emails = list(dict.fromkeys(work_emails + personal_emails + ui_emails + secondary_emails))
            need_sh = bool(len(co_phones) == 0 and source_engine != "signalhire")

            record = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "accountId": acc_id,
                "account": acc_label,
                "fullName": fn,
                "company": cp,
                "headline": hl,
                "workEmails": work_emails,
                "personalEmails": personal_emails,
                "uiEmails": ui_emails,
                "secondaryEmails": secondary_emails,
                "emails": all_emails,
                "phones": co_phones,
                "phoneSource": phone_source,
                "checkedSources": checked_sources,
                "missingSources": exhausted_sources,
                "needSignalHire": need_sh,
                "github": raw_gh,
                "twitter": raw_tw,
                "openalex": openalex_url,
                "orcid": orcid_url,
                "liUrl": target_li_url,
                "apolloChecked": bool("apollo" in checked_sources or is_apollo),
                "coChecked": bool("contactout" in checked_sources or not is_apollo),
                "source": "+".join(checked_sources) if checked_sources else source_engine,
            }

            clean_target_slug = canonical_linkedin_slug(target_li_url)
            norm_target_url = normalize_url(target_li_url)
            norm_target_name = (fn or "").strip().lower()

            existing_idx = None
            for idx, ex in enumerate(self.results):
                ex_url = ex.get("liUrl") or ""
                ex_slug = canonical_linkedin_slug(ex_url)
                if clean_target_slug and ex_slug:
                    if clean_target_slug == ex_slug:
                        existing_idx = idx
                        break
                    continue
                if norm_target_url and ex_url and normalize_url(ex_url) == norm_target_url:
                    existing_idx = idx
                    break
                ex_name = (ex.get("fullName") or "").strip().lower()
                if norm_target_name and ex_name and norm_target_name == ex_name:
                    existing_idx = idx
                    break

            if existing_idx is not None:
                old = self.results[existing_idx]
                for e in (old.get("workEmails") or []):
                    if e not in work_emails:
                        work_emails.append(e)
                for e in (old.get("personalEmails") or []):
                    if e not in personal_emails:
                        personal_emails.append(e)
                for e in (old.get("uiEmails") or []):
                    if e not in ui_emails:
                        ui_emails.append(e)
                for e in (old.get("secondaryEmails") or old.get("uncertainEmails") or []):
                    if e not in secondary_emails and e not in ui_emails:
                        secondary_emails.append(e)
                for p in (old.get("phones") or old.get("coPhones") or []):
                    if p not in co_phones:
                        co_phones.append(p)
                for g in (old.get("github") or []):
                    if g not in raw_gh:
                        raw_gh.append(g)
                for t in (old.get("twitter") or []):
                    if t not in raw_tw:
                        raw_tw.append(t)

                merged_checked = list(dict.fromkeys((old.get("checkedSources") or []) + checked_sources))
                old_missing = old.get("missingSources") or []
                merged_missing = [m for m in list(dict.fromkeys(old_missing + exhausted_sources)) if m not in merged_checked]

                if not openalex_url and old.get("openalex"):
                    openalex_url = old["openalex"]
                if not orcid_url and old.get("orcid"):
                    orcid_url = old["orcid"]
                if not fn and old.get("fullName"):
                    fn = old["fullName"]
                    record["fullName"] = fn
                if not cp and old.get("company"):
                    cp = old["company"]
                    record["company"] = cp
                if not record.get("headline") and old.get("headline"):
                    record["headline"] = old["headline"]

                record["workEmails"] = work_emails
                record["personalEmails"] = personal_emails
                record["uiEmails"] = ui_emails
                record["secondaryEmails"] = [e for e in secondary_emails if e not in ui_emails]
                record["emails"] = list(dict.fromkeys(work_emails + personal_emails + ui_emails + record["secondaryEmails"]))
                record["phones"] = co_phones
                record["phoneSource"] = phone_source or old.get("phoneSource") or ""
                record["checkedSources"] = merged_checked
                record["missingSources"] = merged_missing
                record["needSignalHire"] = bool(len(co_phones) == 0 and "signalhire" not in merged_checked)
                record["github"] = raw_gh
                record["twitter"] = raw_tw
                record["openalex"] = openalex_url
                record["orcid"] = orcid_url
                record["apolloChecked"] = bool("apollo" in merged_checked or old.get("apolloChecked"))
                record["coChecked"] = bool("contactout" in merged_checked or old.get("coChecked"))
                record["source"] = "+".join(merged_checked) if merged_checked else record["source"]

                self.results[existing_idx] = record
            else:
                self.results.insert(0, record)

            safe_write_json(JSON_OUT, self.results)
            self._rewrite_csv()

            sh_note = " | ⚠️ Chờ bấm SignalHire" if record.get("needSignalHire") else f" | Nguồn SĐT: {record.get('phoneSource') or 'Có'}"
            self.add_log(
                f"[+] [{record['source'].upper()} | {acc_label}] ĐÃ GỘP: {record['fullName']} | "
                f"Mail Cty: {len(record['workEmails'])} | Mail Cá nhân: {len(record['personalEmails'])} | "
                f"SĐT: {len(co_phones)}{sh_note}"
            )

    def _rewrite_csv(self) -> None:
        """Xuất CSV tách rõ Email Công Ty, Email Cá Nhân, Số Điện Thoại & Nguồn Extension."""
        headers = [
            "Thời gian",
            "Profile quét",
            "Họ tên",
            "Công ty",
            "Chức danh",
            "Email Công ty (Work)",
            "Email Cá nhân (Personal)",
            "Tất cả Email",
            "Số điện thoại",
            "Nguồn SĐT",
            "Các Extension đã quét",
            "GitHub",
            "Twitter / X",
            "OpenAlex",
            "ORCID",
            "LinkedIn URL",
        ]
        rows = []
        for r in reversed(self.results):
            work_emails = r.get("workEmails") or []
            pers_emails = r.get("personalEmails") or []
            all_emails = r.get("emails") or r.get("uiEmails") or []
            phones = r.get("phones") or r.get("coPhones") or []
            phone_src = r.get("phoneSource") or ""
            checked_src = r.get("checkedSources") or ([r.get("source")] if r.get("source") else [])
            gh = r.get("github") or []
            gh_str = " | ".join(gh) if isinstance(gh, list) else str(gh)
            tw = r.get("twitter") or []
            tw_str = " | ".join(tw) if isinstance(tw, list) else str(tw)
            oa = r.get("openalex") or ""
            if isinstance(oa, dict):
                oa = oa.get("authorUrl") or ""
            orcid = r.get("orcid") or ""

            rows.append([
                r.get("timestamp", ""),
                r.get("account", ""),
                r.get("fullName", ""),
                r.get("company", ""),
                r.get("headline", ""),
                " | ".join(work_emails),
                " | ".join(pers_emails),
                " | ".join(all_emails),
                " | ".join(phones),
                phone_src,
                " + ".join(checked_src),
                gh_str,
                tw_str,
                str(oa),
                str(orcid),
                r.get("liUrl", ""),
            ])
        safe_write_csv(CSV_OUT, rows, headers)


STATE = AppState()


def rotation_worker() -> None:
    """Chạy tuần tự từng Profile một (Cách 1: mỗi lần mở 1 Profile xử lý 5 URL bằng cả 5 Extension tự động + thác nước SĐT)."""
    try:
        with STATE.lock:
            STATE.current_phase = "multi"
            STATE.reload_urls_from_file(phase="multi")
            total_pending = len(STATE.pending_urls)
            if total_pending == 0:
                STATE.add_log("=== TẤT CẢ ỨNG VIÊN TRONG DANH SÁCH ĐÃ ĐƯỢC QUÉT ĐỦ NGUỒN! ===")
                STATE.is_running = False
                return

            enabled_accs = [
                a
                for a in sorted(STATE.accounts, key=lambda x: (x.get("priority", 99), x["id"]))
                if a.get("enabled", True)
            ]
            if not enabled_accs:
                STATE.add_log("[!] Chưa có Profile nào được bật!")
                STATE.is_running = False
                return

            STATE.add_log(
                f"=== BẮT ĐẦU CHẠY TUẦN TỰ CÁCH 1 ({URLS_PER_PROFILE_SESSION} LINK / PROFILE) CHO {total_pending} ỨNG VIÊN TRÊN {len(enabled_accs)} PROFILE ==="
            )

        for idx, acc_item in enumerate(enabled_accs, start=1):
            if STATE.stop_requested:
                break

            acc_id = acc_item["id"]
            with STATE.lock:
                if not STATE.pending_urls:
                    break
                acc = next((a for a in STATE.accounts if a["id"] == acc_id), None)
                if not acc or not acc.get("enabled", True):
                    continue

                cr = acc.get("credits") or {}
                auto_sum = sum(int(cr.get(k, 0)) for k in ["contactout", "kendo", "snov", "apollo", "lusha"])
                if auto_sum <= 0:
                    STATE.add_log(f"[-] Bỏ qua [{acc['name']}] vì cả 5 Extension tự động đều đã hết sạch credit.")
                    continue

                STATE.active_acc_id = acc["id"]
                STATE.acc_used_in_session = 0
                STATE.acc_exhausted = False
                target_url = None
                while STATE.pending_urls:
                    cand = STATE.pending_urls.pop(0)
                    if STATE.is_already_collected(cand, phase="multi"):
                        continue
                    target_url = cand
                    break

                if not target_url:
                    break

                STATE.in_progress_url = target_url
                STATE.in_progress_since = time.time()
                STATE.next_allowed_time = time.time()
                STATE.force_refresh_credits = True
                acc_snapshot = dict(acc)

            profile_dir = PROFILES_DIR / acc_snapshot["id"]
            adspower_id = (acc_snapshot.get("adspowerId") or "").strip()
            mode_label = f"AdsPower ID: {adspower_id}" if adspower_id else f"Local Profile: {acc_snapshot['id']}"
            STATE.add_log(
                f">>> CA {idx}/{len(enabled_accs)}: Mở [{acc_snapshot['name']}] ({mode_label} | Gmail: {acc_snapshot.get('gmail') or 'N/A'}) <<<"
            )
            STATE.add_log(
                f"[6-EXT | {acc_snapshot['name']}] Mở hồ sơ đầu tiên trong ca: {target_url} (Còn {len(STATE.pending_urls)} link chờ)"
            )
            proc = launch_chrome_profile(acc_snapshot, [target_url], engine_mode="multi")
            STATE.active_proc = proc

            try:
                while not STATE.stop_requested:
                    time.sleep(1.2)
                    if proc is not None and proc.poll() is not None:
                        STATE.add_log(f"[!] Trình duyệt của [{acc_snapshot['name']}] đã được đóng.")
                        STATE.reclaim_in_progress_url(reason="Trình duyệt đóng đột ngột")
                        break
                    elif proc is None and adspower_id and not is_adspower_profile_active(adspower_id):
                        STATE.add_log(f"[!] Trình duyệt AdsPower [{acc_snapshot['name']}] đã được đóng.")
                        STATE.reclaim_in_progress_url(reason="AdsPower đóng đột ngột")
                        break

                    with STATE.lock:
                        is_timeout = (
                            STATE.in_progress_url is not None
                            and (time.time() - STATE.in_progress_since) > TASK_TIMEOUT_SEC
                        )
                    if is_timeout:
                        stuck = STATE.in_progress_url
                        STATE.add_log(f"[!] Quá {TASK_TIMEOUT_SEC}s không phản hồi ở {stuck}. Thu hồi link và chuyển sang Profile tiếp theo...")
                        STATE.reclaim_in_progress_url(reason=f"Timeout {TASK_TIMEOUT_SEC}s")
                        with STATE.lock:
                            STATE.acc_exhausted = True

                    with STATE.lock:
                        done_acc = (
                            STATE.acc_exhausted
                            or (not STATE.pending_urls and STATE.in_progress_url is None)
                        )

                    if done_acc:
                        time.sleep(2.5)
                        break
            finally:
                STATE.reclaim_in_progress_url(reason="Kết thúc ca làm việc của Profile")
                STATE.add_log(f"[-] Đang đóng trình duyệt của [{acc_snapshot['name']}] và lưu sổ cái Credit...")
                if adspower_id:
                    stop_adspower_profile(adspower_id)
                else:
                    kill_chrome_for_profile(proc, profile_dir)
                with STATE.lock:
                    STATE.active_proc = None
                    STATE.active_acc_id = None
                    STATE.sync_all_accounts_from_disk()

            if STATE.stop_requested:
                break

            with STATE.lock:
                rem = len(STATE.pending_urls)
            if rem > 0 and idx < len(enabled_accs):
                rest_s = random.randint(MIN_DELAY_BETWEEN_ACCS, MAX_DELAY_BETWEEN_ACCS)
                STATE.add_log(f"[*] Nghỉ chuyển ca {rest_s} giây trên IP công ty trước khi mở Profile tiếp theo (còn {rem} hồ sơ)...")
                for _ in range(rest_s):
                    if STATE.stop_requested:
                        break
                    time.sleep(1.0)

        STATE.add_log("=== ĐÃ HOÀN TẤT PHIÊN CHẠY TUẦN TỰ ĐA EXTENSION — KIỂM TRA TAB 'CỨU NÉT SIGNALHIRE' NẾU CÓ HỒ SƠ KHUYẾT SĐT ===")
    finally:
        STATE.reclaim_in_progress_url(reason="Kết thúc toàn bộ phiên xoay vòng")
        with STATE.lock:
            STATE.is_running = False
            STATE.stop_requested = False
            STATE.active_acc_id = None


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
  <title>ContactOut Multi-Account Control Center</title>
  <style>
    :root {
      --bg: #080b13;
      --bg-soft: #0e1420;
      --card: #111a2b;
      --card-2: #0f1726;
      --card-hover: #152033;
      --border: #203049;
      --border-soft: #1b2740;
      --text: #eef2fa;
      --muted: #8795ad;
      --primary: #5b8cff;
      --primary-hover: #4571f0;
      --emerald: #19d4a2;
      --amber: #f7b23b;
      --rose: #f4556e;
      --violet: #9d74ff;
      --cyan: #28cfe8;
      --primary-soft: rgba(91, 140, 255, 0.14);
      --radius: 18px;
      --radius-sm: 11px;
      --shadow: 0 12px 32px -14px rgba(0, 0, 0, 0.6);
      --shadow-lg: 0 28px 60px -18px rgba(0, 0, 0, 0.7);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    ::selection { background: rgba(91, 140, 255, 0.35); color: #fff; }
    html { scroll-behavior: smooth; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: var(--text);
      min-height: 100vh;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
      background:
        radial-gradient(1100px 600px at 12% -10%, rgba(91, 140, 255, 0.12), transparent 60%),
        radial-gradient(1000px 560px at 100% 0%, rgba(157, 116, 255, 0.10), transparent 55%),
        radial-gradient(900px 600px at 50% 120%, rgba(25, 212, 162, 0.07), transparent 60%),
        var(--bg);
      background-attachment: fixed;
    }
    ::-webkit-scrollbar { width: 11px; height: 11px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #243450; border-radius: 99px; border: 3px solid transparent; background-clip: padding-box; }
    ::-webkit-scrollbar-thumb:hover { background: #324a6b; }
    /* Header & Navigation */
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 15px 30px;
      background: rgba(10, 15, 25, 0.72);
      border-bottom: 1px solid var(--border-soft);
      position: sticky;
      top: 0;
      z-index: 100;
      backdrop-filter: blur(18px) saturate(140%);
      -webkit-backdrop-filter: blur(18px) saturate(140%);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 13px;
      font-weight: 700;
      font-size: 17px;
      letter-spacing: -0.02em;
    }
    .brand-logo {
      width: 40px; height: 40px;
      border-radius: 12px;
      display: grid; place-items: center;
      font-size: 20px;
      background: linear-gradient(135deg, var(--primary), var(--violet));
      box-shadow: 0 8px 20px -6px rgba(91, 140, 255, 0.65);
    }
    .brand-title { display: flex; flex-direction: column; line-height: 1.2; }
    .brand-title b { font-weight: 800; letter-spacing: -0.02em; font-size: 16px; }
    .brand-title small { font-size: 11px; font-weight: 600; color: var(--muted); letter-spacing: 0.02em; display: flex; align-items: center; gap: 6px; }
    .brand-dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--emerald);
      box-shadow: 0 0 0 4px rgba(25, 212, 162, 0.16), 0 0 14px var(--emerald);
      animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 0 4px rgba(25, 212, 162, 0.16), 0 0 14px var(--emerald); }
      50% { box-shadow: 0 0 0 7px rgba(25, 212, 162, 0.04), 0 0 22px var(--emerald); }
    }
    .nav-tabs {
      display: flex;
      gap: 4px;
      background: rgba(8, 12, 22, 0.6);
      padding: 5px;
      border-radius: 14px;
      border: 1px solid var(--border-soft);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
    }
    .nav-btn {
      padding: 9px 18px;
      border-radius: 10px;
      border: none;
      background: transparent;
      color: var(--muted);
      font-weight: 600;
      font-size: 13.5px;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(.4,0,.2,1);
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }
    .nav-btn:hover { color: var(--text); background: rgba(255,255,255,0.04); }
    .nav-btn.active {
      background: linear-gradient(135deg, var(--primary), var(--primary-hover));
      color: #fff;
      box-shadow: 0 8px 20px -6px rgba(91, 140, 255, 0.6);
    }
    .status-pill {
      padding: 8px 16px;
      border-radius: 999px;
      font-size: 12.5px;
      font-weight: 600;
      border: 1px solid var(--border);
      background: rgba(8, 12, 22, 0.6);
      display: inline-flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      transition: border-color 0.3s;
    }
    .container {
      max-width: 1380px;
      margin: 0 auto;
      padding: 28px 30px 48px;
    }
    .page { display: none; animation: fadeIn 0.35s ease; }
    .page.active { display: block; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

    /* Summary Strip */
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 26px;
    }
    .stat-box {
      position: relative;
      background: linear-gradient(160deg, rgba(255,255,255,0.028), rgba(255,255,255,0)), var(--card);
      border: 1px solid var(--border-soft);
      border-radius: var(--radius);
      padding: 18px 20px;
      overflow: hidden;
      transition: transform 0.25s cubic-bezier(.4,0,.2,1), border-color 0.25s, box-shadow 0.25s;
    }
    .stat-box::before {
      content: "";
      position: absolute; inset: 0 0 auto 0; height: 3px;
      background: linear-gradient(90deg, var(--primary), var(--violet));
      opacity: 0.9;
    }
    .stat-box:hover { transform: translateY(-3px); border-color: var(--border); box-shadow: var(--shadow); }
    .stat-top { display: flex; align-items: center; gap: 10px; }
    .stat-ico {
      width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0;
      display: grid; place-items: center; font-size: 16px;
      background: var(--primary-soft); border: 1px solid var(--border-soft);
    }
    .stat-label { font-size: 12px; color: var(--muted); font-weight: 600; letter-spacing: 0.01em; }
    .stat-val { font-size: 25px; font-weight: 800; margin-top: 10px; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .stat-sub { font-size: 11.5px; color: var(--muted); margin-top: 6px; }

    /* Account Cards Grid */
    .section-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .section-title { font-size: 18px; font-weight: 800; letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px; }
    .section-title::before {
      content: ""; width: 4px; height: 20px; border-radius: 99px;
      background: linear-gradient(var(--primary), var(--violet));
    }
    .acc-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
      gap: 18px;
    }
    .acc-card {
      background: linear-gradient(165deg, rgba(255,255,255,0.028), rgba(255,255,255,0)), var(--card);
      border: 1px solid var(--border-soft);
      border-radius: var(--radius);
      padding: 20px;
      transition: transform 0.25s cubic-bezier(.4,0,.2,1), border-color 0.25s, box-shadow 0.25s;
      position: relative;
      overflow: hidden;
    }
    .acc-card:hover { transform: translateY(-3px); border-color: var(--border); box-shadow: var(--shadow); }
    .acc-card.running {
      border-color: rgba(25, 212, 162, 0.55);
      box-shadow: 0 0 0 1px rgba(25, 212, 162, 0.35), 0 16px 40px -14px rgba(25, 212, 162, 0.3);
    }
    .acc-card.running::after {
      content: ""; position: absolute; inset: 0 0 auto 0; height: 3px;
      background: linear-gradient(90deg, var(--emerald), var(--cyan), var(--emerald));
      background-size: 200% 100%;
      animation: shimmer 2.4s linear infinite;
    }
    @keyframes shimmer { to { background-position: -200% 0; } }
    .acc-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 15px;
    }
    .acc-title { font-size: 15.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .acc-email { font-size: 13px; color: var(--cyan); margin-top: 4px; font-weight: 600; }
    .acc-holder { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .badge {
      padding: 4px 11px;
      border-radius: 99px;
      font-size: 11.5px;
      font-weight: 700;
      white-space: nowrap;
    }
    .badge-ok { background: rgba(25, 212, 162, 0.14); color: #4fe6c0; border: 1px solid rgba(25, 212, 162, 0.3); }
    .badge-warn { background: rgba(247, 178, 59, 0.14); color: #fbc966; border: 1px solid rgba(247, 178, 59, 0.3); }
    .badge-err { background: rgba(244, 85, 110, 0.14); color: #ff8699; border: 1px solid rgba(244, 85, 110, 0.3); }
    .badge-run { background: rgba(91, 140, 255, 0.18); color: #9bb6ff; border: 1px solid rgba(91, 140, 255, 0.45); }

    /* Quota Visual Bars (Thanh hiển thị lượt Email & SĐT) */
    .quota-block {
      background: rgba(6, 11, 20, 0.55);
      border: 1px solid var(--border-soft);
      border-radius: 13px;
      padding: 13px 15px;
      margin-bottom: 12px;
    }
    .quota-row-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 9px;
      font-size: 12.5px;
      font-weight: 700;
    }
    .bar-track {
      width: 100%;
      height: 9px;
      background: rgba(255,255,255,0.06);
      border-radius: 99px;
      overflow: hidden;
      margin-bottom: 9px;
    }
    .bar-fill {
      height: 100%;
      border-radius: 99px;
      position: relative;
      overflow: hidden;
      transition: width 0.5s cubic-bezier(.4,0,.2,1), background 0.35s ease;
    }
    .bar-fill::after {
      content: ""; position: absolute; inset: 0;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
      background-size: 200% 100%;
      animation: slide 1.8s linear infinite;
    }
    @keyframes slide { to { background-position: -200% 0; } }
    /* Thanh chia nấc (Segmented Pills) */
    .segments {
      display: grid;
      gap: 5px;
    }
    .seg {
      height: 6px;
      border-radius: 99px;
      background: rgba(255,255,255,0.07);
      transition: all 0.3s ease;
    }
    .seg.active-email { background: linear-gradient(90deg, var(--emerald), var(--cyan)); box-shadow: 0 0 8px rgba(25, 212, 162, 0.5); }
    .seg.active-phone { background: linear-gradient(90deg, var(--violet), var(--primary)); box-shadow: 0 0 8px rgba(157, 116, 255, 0.5); }
    .seg.active-low { background: var(--amber); box-shadow: 0 0 8px rgba(247, 178, 59, 0.5); }

    .acc-actions {
      display: flex;
      gap: 8px;
      margin-top: 15px;
      flex-wrap: wrap;
    }
    .btn {
      padding: 9px 15px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.04);
      color: var(--text);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.12s ease, background 0.18s ease, box-shadow 0.18s ease, border-color 0.18s;
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }
    .btn:hover { background: rgba(255,255,255,0.09); border-color: #2e405c; transform: translateY(-1px); }
    .btn:active { transform: translateY(0) scale(0.98); }
    .btn-primary { background: linear-gradient(135deg, var(--primary), var(--primary-hover)); border-color: transparent; color: #fff; box-shadow: 0 8px 20px -8px rgba(91,140,255,0.7); }
    .btn-primary:hover { background: linear-gradient(135deg, #6d99ff, var(--primary)); box-shadow: 0 12px 26px -8px rgba(91,140,255,0.85); }
    .btn-success { background: linear-gradient(135deg, var(--emerald), #12b388); border-color: transparent; color: #04140f; box-shadow: 0 8px 20px -8px rgba(25,212,162,0.7); }
    .btn-success:hover { background: linear-gradient(135deg, #2fe6b5, var(--emerald)); box-shadow: 0 12px 26px -8px rgba(25,212,162,0.85); }
    .btn-danger { background: linear-gradient(135deg, var(--rose), #e23a56); border-color: transparent; color: #fff; box-shadow: 0 8px 20px -8px rgba(244,85,110,0.7); }
    .btn-danger:hover { background: linear-gradient(135deg, #ff6f87, var(--rose)); box-shadow: 0 12px 26px -8px rgba(244,85,110,0.85); }

        /* Social & Academic Badges */
    .badge-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      max-width: 320px;
    }
    .badge-link {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 9px;
      border-radius: 7px;
      font-size: 11px;
      font-weight: 700;
      text-decoration: none;
      transition: transform 0.12s ease, filter 0.15s ease;
    }
    .badge-link:hover { transform: translateY(-1px); filter: brightness(1.12); }
    .badge-gh { background: #1f2937; color: #f9fafb; border: 1px solid #374151; }
    .badge-gh:hover { background: #374151; }
    .badge-tw { background: #0284c7; color: #fff; }
    .badge-tw:hover { background: #0369a1; }
    .badge-tg { background: #0284c7; color: #fff; }
    .badge-tg:hover { background: #38bdf8; }
    .badge-gravatar { background: #1d4ed8; color: #fff; }
    .badge-gravatar:hover { background: #2563eb; }
    .badge-pat { background: #b45309; color: #fff; }
    .badge-pat:hover { background: #d97706; }
    .badge-sch { background: #4f46e5; color: #fff; }
    .badge-sch:hover { background: #6366f1; }
    .badge-alex { background: #059669; color: #fff; }
    .badge-alex:hover { background: #10b981; }
    .badge-web { background: #334155; color: #e2e8f0; }
    .badge-orcid { background: #a21caf; color: #fff; }
    .badge-pgp { background: #7c3aed; color: #fff; }
    .badge-pgp:hover { background: #6d28d9; }
    .badge-ss { background: #0891b2; color: #fff; }
    .badge-ss:hover { background: #0e7490; }
    .badge-dblp { background: #b45309; color: #fff; }
    .badge-dblp:hover { background: #92400e; }
    .lab-search-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: rgba(14, 165, 233, 0.15);
      border: 1px solid rgba(14, 165, 233, 0.4);
      color: #38bdf8;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 7px;
      border-radius: 4px;
      text-decoration: none;
      margin-top: 4px;
      transition: all 0.15s ease;
    }
    .lab-search-btn:hover {
      background: rgba(14, 165, 233, 0.3);
      color: #fff;
    }

/* Runner Page */
    .runner-layout {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 20px;
    }
    .panel {
      background: linear-gradient(165deg, rgba(255,255,255,0.025), rgba(255,255,255,0)), var(--card);
      border: 1px solid var(--border-soft);
      border-radius: var(--radius);
      padding: 22px;
    }
    textarea.url-input {
      width: 100%;
      height: 270px;
      background: rgba(6, 11, 20, 0.6);
      border: 1px solid var(--border);
      border-radius: 12px;
      color: var(--text);
      padding: 14px;
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 13px;
      line-height: 1.7;
      resize: vertical;
      margin-top: 12px;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    textarea.url-input:focus, .select-input:focus, .text-input:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-soft);
    }
    .log-box {
      width: 100%;
      height: 330px;
      background:
        radial-gradient(520px 130px at 100% 0%, rgba(25,212,162,0.06), transparent 70%),
        #05080f;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      line-height: 1.65;
      color: #86efc7;
      overflow-y: auto;
      white-space: pre-wrap;
    }
    .select-input, .text-input {
      background: rgba(6, 11, 20, 0.6);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 9px 13px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .select-input { cursor: pointer; }

    /* Results Table (Multi-Phone & Multi-Email Chips) */
    .table-wrap {
      background: var(--card);
      border: 1px solid var(--border-soft);
      border-radius: var(--radius);
      overflow: hidden;
      overflow-x: auto;
      box-shadow: var(--shadow);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 14px 16px;
      text-align: left;
      border-bottom: 1px solid var(--border-soft);
      vertical-align: top;
    }
    th {
      background: rgba(10, 15, 25, 0.9);
      backdrop-filter: blur(8px);
      color: var(--muted);
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    tbody tr { transition: background 0.15s; }
    tbody tr:nth-child(even) td { background: rgba(255, 255, 255, 0.012); }
    tbody tr:hover td { background: rgba(91, 140, 255, 0.06); }
    .chip-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 8px;
      font-family: 'JetBrains Mono', 'Consolas', monospace;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      width: fit-content;
      transition: transform 0.12s ease, filter 0.15s ease;
    }
    .chip:hover { transform: translateY(-1px) scale(1.02); filter: brightness(1.15); }
    .chip:active { transform: scale(0.97); }
    .chip-phone {
      background: rgba(157, 116, 255, 0.16);
      color: #c9b6ff;
      border: 1px solid rgba(157, 116, 255, 0.35);
    }
    .chip-email {
      background: rgba(25, 212, 162, 0.14);
      color: #7defc9;
      border: 1px solid rgba(25, 212, 162, 0.32);
    }
    .chip-idx {
      font-size: 10px;
      padding: 1px 6px;
      border-radius: 5px;
      background: rgba(0, 0, 0, 0.35);
      color: var(--muted);
    }
    .toast {
      position: fixed;
      bottom: 26px;
      right: 26px;
      background: linear-gradient(135deg, var(--emerald), #12b388);
      color: #04140f;
      padding: 12px 20px;
      border-radius: 13px;
      font-weight: 700;
      font-size: 13px;
      display: none;
      z-index: 9999;
      box-shadow: 0 16px 40px -10px rgba(25,212,162,0.5), 0 8px 20px rgba(0,0,0,0.4);
      animation: toastIn 0.3s cubic-bezier(.2,.8,.2,1);
    }
    @keyframes toastIn { from { opacity: 0; transform: translateY(14px) scale(0.96); } to { opacity: 1; transform: none; } }

    /* Responsive */
    @media (max-width: 1100px) {
      .summary-grid { grid-template-columns: repeat(2, 1fr); }
      .runner-layout { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .topbar { flex-wrap: wrap; gap: 12px; padding: 14px 18px; }
      .nav-tabs { order: 3; width: 100%; overflow-x: auto; }
      .container { padding: 20px 16px 40px; }
      .summary-grid { grid-template-columns: 1fr; }
      .acc-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>

  <div class="topbar">
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div class="brand-title">
        <b>Argon 6-Extension Orchestrator</b>
        <small><span class="brand-dot" id="topDot"></span> 20 AdsPower Profiles • Dynamic Credit Ledger</small>
      </div>
    </div>
    <div class="nav-tabs">
      <button class="nav-btn active" onclick="switchTab('accounts', this)">📊 Sổ Cái 20 Profile × 6 Ext</button>
      <button class="nav-btn" onclick="switchTab('runner', this)">🚀 Chạy Tuần Tự (5 Link/Ca)</button>
      <button class="nav-btn" onclick="switchTab('signalhire', this)">🎯 Cứu Nét SignalHire (<span id="shCountTab">0</span>)</button>
      <button class="nav-btn" onclick="switchTab('results', this)">📋 Kết Quả Gộp (<span id="resCountTab">0</span>)</button>
    </div>
    <div class="status-pill" id="sysStatusPill">Trạng thái: Đang chờ</div>
  </div>

  <div class="container">
    <!-- Dải thống kê tổng hợp 6 Extension -->
    <div class="summary-grid">
      <div class="stat-box">
        <div class="stat-top"><div class="stat-ico">⚡</div><div class="stat-label">ContactOut (5/ngày) & Lusha (40/tháng)</div></div>
        <div class="stat-val" id="sumEmailText">0 CO • 0 Lusha</div>
        <div class="bar-track" style="margin-top:10px;margin-bottom:0;">
          <div class="bar-fill" id="sumEmailBar" style="width:100%;background:var(--emerald);"></div>
        </div>
      </div>
      <div class="stat-box">
        <div class="stat-top"><div class="stat-ico">📧</div><div class="stat-label">Kendo (50) • Snov (50) • Apollo (80)</div></div>
        <div class="stat-val" id="sumPhoneText">0 Kendo • 0 Snov • 0 Apollo</div>
        <div class="bar-track" style="margin-top:10px;margin-bottom:0;">
          <div class="bar-fill" id="sumPhoneBar" style="width:100%;background:var(--violet);"></div>
        </div>
      </div>
      <div class="stat-box">
        <div class="stat-top"><div class="stat-ico">🎯</div><div class="stat-label">SignalHire Bấm Tay (10/tháng) & Tiến Độ</div></div>
        <div class="stat-val" id="sumQueueText">0 / 0</div>
        <div class="bar-track" style="margin-top:10px;margin-bottom:0;">
          <div class="bar-fill" id="sumQueueBar" style="width:0%;background:var(--amber);"></div>
        </div>
      </div>
      <div class="stat-box">
        <div class="stat-top"><div class="stat-ico">🗂️</div><div class="stat-label">Tổng Hồ Sơ Đã Gộp (Công ty + Cá nhân)</div></div>
        <div class="stat-val" id="sumCollectedText">0 hồ sơ</div>
        <div class="stat-sub" id="sumPhonesDetail">0 SĐT • 0 Email đã lưu</div>
      </div>
    </div>

    <!-- TRANG 1: QUẢN LÝ 20 PROFILE ADSPOWER & SỔ CÁI 6 EXTENSION -->
    <div id="page-accounts" class="page active">
      <div class="section-header">
        <div>
          <div class="section-title">Sổ Cái Tồn Kho Credit (20 Profile AdsPower × 6 Extension)</div>
          <div style="font-size:12.5px;color:var(--muted);margin-top:2px;">
            ContactOut tự hồi 5 lượt mỗi ngày • Email chạy gộp cả 5 nguồn • SĐT chạy thác nước: ContactOut ➔ Lusha ➔ Apollo (8cr) ➔ SignalHire (bấm tay).
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-success" onclick="init20Profiles()">⚡ Khởi tạo nhanh 20 Profile</button>
          <button class="btn btn-primary" onclick="syncAdsPowerApi()">🔄 Đồng bộ từ AdsPower API (50325)</button>
          <button class="btn" onclick="syncDiskCredits()">🔄 Đọc lại LevelDB</button>
          <button class="btn" onclick="addNewAccount()">+ Thêm 1 Profile</button>
        </div>
      </div>

      <div class="acc-grid" id="accGrid"></div>
    </div>

    <!-- TRANG 2: CHẠY THU THẬP LINK -->
    <div id="page-runner" class="page">
      <div class="runner-layout">
        <div class="panel">
          <div class="section-header" style="margin-bottom:8px;">
            <div class="section-title">Danh Sách Link Hồ Sơ LinkedIn Cần Lấy</div>
            <button class="btn" onclick="saveUrlsOnly()">💾 Lưu danh sách link</button>
          </div>
          <div style="font-size:12.5px;color:var(--muted);">
            Mỗi lần mở 1 Profile sẽ chạy tuần tự 5 URL (vét đủ cả 5 nguồn Email + thác nước SĐT), sau đó đóng trình duyệt nghỉ 25-40s rồi chuyển sang Profile kế tiếp.
          </div>
          <textarea id="urlsTextarea" class="url-input" placeholder="https://www.linkedin.com/in/satyanadella/&#10;https://www.linkedin.com/in/jeffweiner08/"></textarea>

          <div style="display:flex;align-items:center;justify-content:space-between;margin-top:16px;flex-wrap:wrap;gap:12px;">
            <div style="display:flex;align-items:center;gap:10px;">
              <label style="font-size:13px;font-weight:600;color:var(--muted);">Chiến thuật chạy:</label>
              <select id="quotaModeSelect" class="select-input">
                <option value="standard">Cách 1: Cuốn chiếu 5 URL / Profile (Gộp 5 nguồn Email + Thác nước SĐT)</option>
                <option value="require_phone">Ưu tiên SĐT tuyệt đối</option>
                <option value="require_email">Ưu tiên Email</option>
              </select>
            </div>
            <div style="display:flex;gap:10px;">
              <button class="btn btn-success" id="btnStartRun" onclick="startRotationRun()">▶ BẮT ĐẦU CHẠY TUẦN TỰ</button>
              <button class="btn btn-danger" id="btnStopRun" onclick="stopRotationRun()" style="display:none;">⏹ DỪNG CHẠY</button>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="section-header" style="margin-bottom:10px;">
            <div class="section-title">Nhật Ký Điều Phối Động (Live Logs)</div>
            <span style="font-size:12px;color:var(--muted);" id="activeAccLabel">Profile đang mở: Không</span>
          </div>
          <div class="log-box" id="logBox"></div>
        </div>
      </div>
    </div>

    <!-- TRANG 3: DANH SÁCH CẦN BẤM TAY SIGNALHIRE (PHƯƠNG ÁN B) -->
    <div id="page-signalhire" class="page">
      <div class="section-header">
        <div>
          <div class="section-title">🎯 Danh Sách Hồ Sơ Khuyết SĐT — Chờ Bấm Tay SignalHire (10 Credit/Tháng)</div>
          <div style="font-size:12.5px;color:var(--muted);margin-top:2px;">
            Đây là những hồ sơ đã chạy qua cả 3 tầng tự động (ContactOut ➔ Lusha ➔ Apollo) mà vẫn chưa ra SĐT. Bấm nút bên cạnh để mở đúng Profile còn lượt SignalHire và tự tay bấm Reveal.
          </div>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ứng viên & Công ty</th>
              <th>Email đã thu thập được</th>
              <th>Các nguồn tự động đã thử</th>
              <th>Hồ sơ LinkedIn</th>
              <th>Hành động cứu nét (SignalHire)</th>
            </tr>
          </thead>
          <tbody id="shTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- TRANG 4: BẢNG KẾT QUẢ GỘP ĐA NGUỒN -->
    <div id="page-results" class="page">
      <div class="section-header">
        <div>
          <div class="section-title">Kết Quả Đã Gộp (Tách Email Công Ty • Email Cá Nhân • SĐT & Nguồn)</div>
          <div style="font-size:12.5px;color:var(--muted);margin-top:2px;">
            Bấm vào bất kỳ thẻ Số điện thoại hoặc Email nào để copy nhanh.
          </div>
        </div>
        <div style="display:flex;gap:10px;">
          <button class="btn btn-primary" onclick="exportCsvFile()">📥 Xuất File CSV (ket_qua.csv)</button>
          <button class="btn" onclick="openResultFolder()">📂 Mở thư mục kết quả</button>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Thời gian / Profile</th>
              <th>Họ tên & Chức danh</th>
              <th>Số điện thoại (Nguồn)</th>
              <th>Email Công ty (Work)</th>
              <th>Email Cá nhân (Personal)</th>
              <th>Nguồn đã quét</th>
              <th>MXH / Học thuật</th>
              <th>Hồ sơ LinkedIn</th>
            </tr>
          </thead>
          <tbody id="resultsTbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="toast" id="toastBox">Đã copy!</div>

  <script>
    let urlsLoadedOnce = false;
    let lastAccountsSig = '';
    let lastResultsSig = '';

    function showToast(msg) {
      const t = document.getElementById('toastBox');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2200);
    }

    function copyText(txt) {
      navigator.clipboard.writeText(txt);
      showToast('Đã copy: ' + txt);
    }

    function switchTab(name, btn) {
      document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      document.getElementById('page-' + name).classList.add('active');
      btn.classList.add('active');
    }

    function badgeColorForCredit(val, maxVal) {
      if (val <= 0) return 'background:rgba(244,85,110,0.15);color:#ff8699;border:1px solid rgba(244,85,110,0.35);';
      if (val / maxVal <= 0.25) return 'background:rgba(247,178,59,0.16);color:#fbc966;border:1px solid rgba(247,178,59,0.38);';
      return 'background:rgba(25,212,162,0.14);color:#4fe6c0;border:1px solid rgba(25,212,162,0.32);';
    }

    function renderAccounts(accounts, activeAccId, manualAccId) {
      let sumCO = 0, sumKendo = 0, sumApollo = 0, sumSnov = 0, sumLusha = 0, sumSH = 0;
      accounts.forEach(acc => {
        const cr = acc.credits || {};
        sumCO += Number(cr.contactout ?? 5);
        sumKendo += Number(cr.kendo ?? 50);
        sumApollo += Number(cr.apollo ?? 80);
        sumSnov += Number(cr.snov ?? 50);
        sumLusha += Number(cr.lusha ?? 40);
        sumSH += Number(cr.signalhire ?? 10);
      });

      document.getElementById('sumEmailText').textContent = `${sumCO} CO • ${sumLusha} Lusha`;
      document.getElementById('sumPhoneText').textContent = `${sumKendo} Kendo • ${sumSnov} Snov • ${sumApollo} Apollo`;

      const sig = JSON.stringify({ accounts, activeAccId, manualAccId });
      if (sig === lastAccountsSig) return;
      lastAccountsSig = sig;

      const grid = document.getElementById('accGrid');
      grid.innerHTML = accounts.map(acc => {
        const cr = acc.credits || { contactout: 5, kendo: 50, apollo: 80, snov: 50, lusha: 40, signalhire: 10 };
        const isRunningThis = (acc.id === activeAccId || acc.id === manualAccId);
        let statusBadge = '';
        if (acc.id === activeAccId) {
          statusBadge = `<span class="badge badge-run">⚡ Đang chạy tuần tự</span>`;
        } else if (acc.id === manualAccId) {
          statusBadge = `<span class="badge badge-run">🌐 Đang mở trình duyệt</span>`;
        } else if ((cr.contactout || 0) <= 0) {
          statusBadge = `<span class="badge badge-warn">Hết CO hôm nay (Còn nguồn tháng)</span>`;
        } else {
          statusBadge = `<span class="badge badge-ok">Sẵn sàng (${cr.contactout}/5 CO)</span>`;
        }

        const displayTitle = acc.customName || acc.holderName || acc.name;
        const apIdText = acc.adspowerId ? `AdsPower ID: <b>${acc.adspowerId}</b>` : `Local Profile: profiles/${acc.id}`;

        const extItems = [
          ['contactout', 'ContactOut (Ngày)', cr.contactout ?? 5, 5],
          ['lusha', 'Lusha (Tháng)', cr.lusha ?? 40, 40],
          ['kendo', 'Kendo (Tháng)', cr.kendo ?? 50, 50],
          ['snov', 'Snov.io (Tháng)', cr.snov ?? 50, 50],
          ['apollo', 'Apollo (1E/8P)', cr.apollo ?? 80, 80],
          ['signalhire', 'SignalHire (Tay)', cr.signalhire ?? 10, 10],
        ];

        const matrixHtml = extItems.map(([key, label, val, maxV]) => `
          <div style="padding:7px 9px;border-radius:9px;display:flex;justify-content:space-between;align-items:center;font-size:12px;${badgeColorForCredit(val, maxV)}">
            <span style="font-weight:600;">${label}</span>
            <b style="font-family:'JetBrains Mono',monospace;">${val}/${maxV}</b>
          </div>
        `).join('');

        return `
          <div class="acc-card ${isRunningThis ? 'running' : ''}">
            <div class="acc-header">
              <div>
                <div class="acc-title">
                  <input type="checkbox" ${acc.enabled !== false ? 'checked' : ''} onchange="toggleAccEnabled('${acc.id}', this.checked)" title="Bật/Tắt Profile này" />
                  <span>${displayTitle}</span>
                  <span style="font-size:12px;color:var(--muted);font-weight:400;">(${acc.id})</span>
                  <span style="font-size:11px;padding:2px 7px;border-radius:4px;background:#1e293b;color:var(--cyan);font-weight:700;">Ca #${acc.priority || 1}</span>
                </div>
                <div class="acc-email">📧 ${acc.gmail || acc.accountEmail || 'Chưa gắn Gmail'}</div>
                <div class="acc-holder">🖥️ ${apIdText}</div>
              </div>
              ${statusBadge}
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:12px;">
              ${matrixHtml}
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:8px;">
              <input type="text" class="text-input" style="font-size:12px;" placeholder="AdsPower User ID (VD: k12abc)" value="${acc.adspowerId || ''}" onchange="updateAccField('${acc.id}', { adspowerId: this.value })" />
              <input type="text" class="text-input" style="font-size:12px;" placeholder="Gmail đăng ký 6 nơi" value="${acc.gmail || ''}" onchange="updateAccField('${acc.id}', { gmail: this.value })" />
            </div>

            <div class="acc-actions">
              <button class="btn btn-success" onclick="setRunFirst('${acc.id}')">⭐ Chạy đầu</button>
              <button class="btn btn-primary" onclick="openAccBrowser('${acc.id}')">🌐 Mở Trình Duyệt</button>
              <button class="btn" onclick="editAll6Credits('${acc.id}', ${cr.contactout ?? 5}, ${cr.kendo ?? 50}, ${cr.apollo ?? 80}, ${cr.snov ?? 50}, ${cr.lusha ?? 40}, ${cr.signalhire ?? 10})">✏️ Sửa Credit</button>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderResults(results) {
      document.getElementById('resCountTab').textContent = results.length;
      document.getElementById('sumCollectedText').textContent = results.length + ' hồ sơ';

      const needShList = results.filter(r => {
        const ph = Array.isArray(r.phones) ? r.phones : [];
        return ph.length === 0 || r.needSignalHire;
      });
      document.getElementById('shCountTab').textContent = needShList.length;

      const sig = JSON.stringify(results);
      if (sig === lastResultsSig) return;
      lastResultsSig = sig;

      // Render bảng Cứu nét SignalHire (Phương án B)
      const shTbody = document.getElementById('shTbody');
      if (needShList.length === 0) {
        shTbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:28px;">🎉 Tuyệt vời! Không có hồ sơ nào bị khuyết SĐT cần cứu nét bằng SignalHire.</td></tr>`;
      } else {
        shTbody.innerHTML = needShList.map(r => {
          const allE = Array.isArray(r.emails) ? r.emails : [];
          const checked = Array.isArray(r.checkedSources) ? r.checkedSources.join(' + ') : (r.source || 'multi');
          return `
            <tr>
              <td>
                <div style="font-weight:700;font-size:14px;">${r.fullName || 'Chưa rõ tên'}</div>
                <div style="font-size:12px;color:var(--cyan);">${r.company || ''}</div>
                <div style="font-size:11.5px;color:var(--muted);">${r.headline || ''}</div>
              </td>
              <td>
                ${allE.length > 0 ? allE.map(e => `<div class="chip chip-email" onclick="copyText('${e}')">✉️ ${e}</div>`).join('') : '<span style="color:var(--rose);">Chưa có Email</span>'}
              </td>
              <td><span class="badge badge-warn">${checked}</span></td>
              <td><a href="${r.liUrl || '#'}" target="_blank" style="color:var(--primary);font-size:12.5px;">${r.liUrl || ''}</a></td>
              <td>
                <button class="btn btn-primary" style="background:linear-gradient(135deg,#f59e0b,#d97706);color:#080d18;font-weight:800;" onclick="openSignalHireRescue('${(r.liUrl || '').replace(/'/g, "\\'")}')">
                  🎯 Mở Profile còn SignalHire để bấm
                </button>
              </td>
            </tr>
          `;
        }).join('');
      }

      let totalPhones = 0, totalEmails = 0;
      const tbody = document.getElementById('resultsTbody');

      tbody.innerHTML = results.map(r => {
        const phones = Array.isArray(r.phones) && r.phones.length > 0
          ? r.phones
          : (Array.isArray(r.coPhones) ? r.coPhones : (Array.isArray(r.uiPhones) ? r.uiPhones : []));

        const workEmails = Array.isArray(r.workEmails) ? r.workEmails : [];
        const personalEmails = Array.isArray(r.personalEmails) ? r.personalEmails : [];
        const fallbackEmails = Array.isArray(r.emails) ? r.emails : [];

        const displayWork = workEmails.length > 0 ? workEmails : fallbackEmails.filter(e => !e.endsWith('@gmail.com') && !e.endsWith('@yahoo.com') && !e.endsWith('@hotmail.com') && !e.endsWith('@outlook.com'));
        const displayPers = personalEmails.length > 0 ? personalEmails : fallbackEmails.filter(e => e.endsWith('@gmail.com') || e.endsWith('@yahoo.com') || e.endsWith('@hotmail.com') || e.endsWith('@outlook.com'));

        totalPhones += phones.length;
        totalEmails += (displayWork.length + displayPers.length);

        let phonesHtml = '';
        if (phones.length > 0) {
          phonesHtml = '<div class="chip-list">';
          for (let i = 0; i < phones.length; i++) {
            const p = phones[i];
            phonesHtml += `
              <div class="chip chip-phone" onclick="copyText('${p.replace(/'/g, "\\'")}')">
                <span class="chip-idx">#${i + 1}</span>
                <span>📞 ${p}</span>
              </div>`;
          }
          if (r.phoneSource) {
            phonesHtml += `<span style="font-size:11px;color:var(--emerald);font-weight:700;">Nguồn SĐT: ${r.phoneSource.toUpperCase()}</span>`;
          }
          phonesHtml += '</div>';
        } else {
          phonesHtml = `<span style="color:var(--amber);font-size:12px;font-weight:600;">⚠️ Chưa có SĐT (Chờ SignalHire)</span>`;
        }

        const workHtml = displayWork.length > 0
          ? '<div class="chip-list">' + displayWork.map(e => `<div class="chip chip-email" onclick="copyText('${e.replace(/'/g, "\\'")}')">🏢 ${e}</div>`).join('') + '</div>'
          : '<span style="color:var(--muted);font-size:12px;">—</span>';

        const persHtml = displayPers.length > 0
          ? '<div class="chip-list">' + displayPers.map(e => `<div class="chip chip-email" style="background:rgba(56,189,248,0.14);color:#7dd3fc;border-color:rgba(56,189,248,0.35);" onclick="copyText('${e.replace(/'/g, "\\'")}')">👤 ${e}</div>`).join('') + '</div>'
          : '<span style="color:var(--muted);font-size:12px;">—</span>';

        const checkedArr = Array.isArray(r.checkedSources) && r.checkedSources.length > 0 ? r.checkedSources : (r.source ? [r.source] : []);
        const checkedHtml = checkedArr.map(s => `<span class="badge badge-ok" style="display:inline-block;margin:2px;">${s}</span>`).join('');

        const ghList = Array.isArray(r.github) ? r.github : (r.github ? [r.github] : []);
        const twList = Array.isArray(r.twitter) ? r.twitter : (r.twitter ? [r.twitter] : []);
        const socialBadges = [
          ...ghList.map(u => `<a class="badge-link badge-gh" href="${u}" target="_blank">💻 GitHub</a>`),
          ...twList.map(u => `<a class="badge-link badge-tw" href="${u}" target="_blank">🐦 X</a>`),
        ].join(' ') || '<span style="color:var(--muted);font-size:12px;">—</span>';

        return `
          <tr>
            <td>
              <div style="font-weight:600;color:var(--primary);">${r.account || r.accountId || ''}</div>
              <div style="font-size:11.5px;color:var(--muted);">${r.timestamp || ''}</div>
            </td>
            <td>
              <div style="font-weight:700;font-size:14px;">${r.fullName || 'Chưa rõ tên'}</div>
              <div style="font-size:12px;color:var(--cyan);">${r.company || ''}</div>
              <div style="font-size:11.5px;color:var(--muted);max-width:260px;">${r.headline || ''}</div>
            </td>
            <td>${phonesHtml}</td>
            <td>${workHtml}</td>
            <td>${persHtml}</td>
            <td>${checkedHtml}</td>
            <td>${socialBadges}</td>
            <td>
              <a href="${r.liUrl || '#'}" target="_blank" style="color:var(--primary);font-size:12.5px;word-break:break-all;">${r.liUrl || ''}</a>
            </td>
          </tr>
        `;
      }).join('');

      document.getElementById('sumPhonesDetail').textContent = `${totalPhones} SĐT • ${totalEmails} Email đã gộp`;
    }

    async function fetchState() {
      try {
        const res = await fetch('/api/state');
        const data = await res.json();

        renderAccounts(data.accounts || [], data.activeAccId, data.manualAccId);
        renderResults(data.results || []);

        if (!urlsLoadedOnce && typeof data.rawUrls === 'string') {
          document.getElementById('urlsTextarea').value = data.rawUrls;
          urlsLoadedOnce = true;
        }

        const totalU = data.totalCampaignUrls || 0;
        const remU = data.pendingUrlsCount || 0;
        const doneU = Math.max(0, totalU - remU);
        let sumSH = 0;
        (data.accounts || []).forEach(a => { sumSH += Number((a.credits || {}).signalhire ?? 10); });
        document.getElementById('sumQueueText').textContent = `${sumSH} SH • ${doneU}/${totalU} link`;
        document.getElementById('sumQueueBar').style.width = (totalU ? Math.round((doneU / totalU) * 100) : 0) + '%';

        const logBox = document.getElementById('logBox');
        const newLogs = (data.logs || []).join('\n');
        if (logBox.textContent !== newLogs) {
          logBox.textContent = newLogs;
          logBox.scrollTop = logBox.scrollHeight;
        }

        const btnStart = document.getElementById('btnStartRun');
        const btnStop = document.getElementById('btnStopRun');
        const pill = document.getElementById('sysStatusPill');
        const dot = document.getElementById('topDot');

        if (data.isRunning) {
          btnStart.style.display = 'none';
          btnStop.style.display = 'inline-flex';
          pill.textContent = '⚡ Đang chạy tuần tự (' + (data.activeAccId || '') + ')';
          pill.style.borderColor = 'var(--emerald)';
          dot.style.background = 'var(--emerald)';
        } else {
          btnStart.style.display = 'inline-flex';
          btnStop.style.display = 'none';
          pill.textContent = 'Trạng thái: Sẵn sàng';
          pill.style.borderColor = 'var(--border)';
        }
        document.getElementById('activeAccLabel').textContent = 'Profile đang mở: ' + (data.activeAccId || data.manualAccId || 'Không');
      } catch (e) {}
    }

    async function apiPost(path, body) {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      });
      const data = await res.json();
      await fetchState();
      return data;
    }

    async function init20Profiles() {
      const res = await apiPost('/api/init_20_profiles', {});
      showToast(`Đã khởi tạo ${res.created || 0} Profile mới (Đủ 20 Profile)!`);
    }

    async function syncAdsPowerApi() {
      const res = await apiPost('/api/sync_adspower', {});
      if (res.synced > 0) {
        showToast(`Đã đồng bộ ${res.synced} Profile từ AdsPower Local API!`);
      } else {
        alert('Không kết nối được AdsPower API (127.0.0.1:50325) hoặc chưa mở phần mềm AdsPower!');
      }
    }

    async function syncDiskCredits() {
      await apiPost('/api/sync_disk', {});
      showToast('Đã đồng bộ lại dữ liệu!');
    }

    async function setRunFirst(accId) {
      await apiPost('/api/set_priority_acc', { accId });
      showToast('Đã đặt ' + accId + ' chạy đầu tiên!');
    }

    async function toggleAccEnabled(accId, enabled) {
      await apiPost('/api/update_acc', { accId, enabled });
      showToast((enabled ? 'Đã bật ' : 'Đã tắt ') + accId);
    }

    async function updateAccField(accId, patch) {
      await apiPost('/api/update_acc', { accId, ...patch });
      showToast('Đã lưu cấu hình cho ' + accId);
    }

    async function editAll6Credits(accId, co, kendo, apollo, snov, lusha, sh) {
      const raw = prompt(
        `Nhập số dư Credit của ${accId} theo thứ tự:\nContactOut, Kendo, Apollo, Snov, Lusha, SignalHire`,
        `${co}, ${kendo}, ${apollo}, ${snov}, ${lusha}, ${sh}`
      );
      if (!raw) return;
      const parts = raw.split(',').map(s => parseInt(s.trim(), 10));
      if (parts.length < 6) return alert('Vui lòng nhập đủ 6 số cách nhau bởi dấu phẩy!');
      await apiPost('/api/update_acc', {
        accId,
        credits: {
          contactout: isNaN(parts[0]) ? co : parts[0],
          kendo: isNaN(parts[1]) ? kendo : parts[1],
          apollo: isNaN(parts[2]) ? apollo : parts[2],
          snov: isNaN(parts[3]) ? snov : parts[3],
          lusha: isNaN(parts[4]) ? lusha : parts[4],
          signalhire: isNaN(parts[5]) ? sh : parts[5],
        }
      });
      showToast('Đã cập nhật sổ cái 6 Extension cho ' + accId);
    }

    async function openAccBrowser(accId) {
      showToast('Đang mở trình duyệt cho ' + accId + '...');
      await apiPost('/api/open_acc', { accId });
    }

    async function openSignalHireRescue(liUrl) {
      showToast('Đang mở Profile còn lượt SignalHire cho hồ sơ này...');
      const res = await apiPost('/api/open_signalhire_rescue', { liUrl });
      if (res.error) alert(res.error);
    }

    async function addNewAccount() {
      const name = prompt('Nhập tên hiển thị cho Profile mới:', 'AdsPower Profile mới');
      if (!name) return;
      await apiPost('/api/add_acc', { name });
      showToast('Đã thêm ' + name);
    }

    async function saveUrlsOnly() {
      const rawUrls = document.getElementById('urlsTextarea').value;
      await apiPost('/api/save_urls', { rawUrls });
      showToast('Đã lưu danh sách link vào urls.txt!');
    }

    async function startRotationRun() {
      const rawUrls = document.getElementById('urlsTextarea').value;
      const quotaMode = document.getElementById('quotaModeSelect').value;
      const res = await apiPost('/api/start_run', { rawUrls, quotaMode });
      if (res.error) {
        alert(res.error);
      } else {
        showToast('Đã bắt đầu chạy tuần tự 5 URL / Profile!');
      }
    }

    async function stopRotationRun() {
      await apiPost('/api/stop_run', {});
      showToast('Đã gửi lệnh dừng!');
    }

    function exportCsvFile() {
      fetch('/download_csv')
        .then(res => {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.blob();
        })
        .then(blob => {
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.style.display = 'none';
          a.href = url;
          a.download = 'ket_qua.csv';
          document.body.appendChild(a);
          a.click();
          setTimeout(() => {
            a.remove();
            window.URL.revokeObjectURL(url);
          }, 1000);
          showToast('Đã tải xuống file ket_qua.csv thành công!');
        })
        .catch(err => {
          alert('Lỗi xuất file CSV: ' + err.message);
        });
    }

    async function openResultFolder() {
      await apiPost('/api/open_folder', {});
      showToast('Đang mở thư mục chứa file kết quả...');
    }

    fetchState();
    setInterval(fetchState, 2000);
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def _is_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        origin_clean = origin.strip().lower()
        if "linkedin.com" in origin_clean:
            return False
        if origin_clean.startswith("chrome-extension://"):
            return True
        try:
            parsed = urllib.parse.urlparse(origin_clean)
            hostname = parsed.hostname
            if hostname in ("127.0.0.1", "localhost", "::1"):
                return True
        except Exception:
            pass
        return False

    def _send_forbidden(self) -> None:
        body = b'{"error": "forbidden", "message": "Cross-origin request blocked"}'
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        if origin and self._is_origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin.strip())
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8765")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self._is_origin_allowed():
            self._send_forbidden()
            return
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if not self._is_origin_allowed():
            self._send_forbidden()
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML)
            return

        if path == "/api/state":
            with STATE.lock:
                STATE.sync_all_accounts_from_disk()
                payload = {
                    "accounts": STATE.accounts,
                    "results": STATE.results,
                    "logs": STATE.logs[-80:],
                    "isRunning": STATE.is_running,
                    "currentPhase": STATE.current_phase,
                    "activeAccId": STATE.active_acc_id,
                    "manualAccId": STATE.manual_acc_id,
                    "pendingUrlsCount": len(STATE.pending_urls),
                    "totalCampaignUrls": STATE.total_campaign_urls,
                    "rawUrls": STATE.get_raw_urls_text(),
                    "quotaMode": STATE.quota_mode,
                }
            self._send_json(200, payload)
            return

        if path == "/task_plan":
            qs = urllib.parse.parse_qs(parsed.query)
            li_url = (qs.get("liUrl", [""])[0] or "").strip()
            plan = STATE.get_task_plan(li_url)
            self._send_json(200, plan)
            return

        if path == "/download_csv":
            with STATE.lock:
                STATE._rewrite_csv()
                data = b""
                if CSV_OUT.exists():
                    try:
                        data = CSV_OUT.read_bytes()
                    except (PermissionError, OSError):
                        pass
                if not data:
                    backups = sorted(BASE_DIR.glob("ket_qua_backup_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
                    if backups:
                        try:
                            data = backups[0].read_bytes()
                        except Exception:
                            pass
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8-sig")
            self.send_header("Content-Disposition", 'attachment; filename="ket_qua.csv"')
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/next_url":
            qs = urllib.parse.parse_qs(parsed.query)
            req_engine = (qs.get("engine", ["multi"])[0] or "multi").strip().lower()
            res = STATE.get_next_url_for_browser(requested_engine=req_engine)
            self._send_json(200, res)
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._is_origin_allowed():
            self._send_forbidden()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}

        if self.path == "/account_status":
            STATE.update_live_account_status(data)
            self._send_json(200, {"ok": True})
            return

        if self.path == "/result":
            STATE.handle_result_from_browser(data)
            self._send_json(200, {"saved": True})
            return

        if self.path == "/api/init_20_profiles":
            created = STATE.init_20_adspower_profiles()
            STATE.add_log(f"[+] Đã khởi tạo nhanh 20 Profile AdsPower (tạo mới {created} mục) với đủ sổ cái 6 Extension.")
            self._send_json(200, {"ok": True, "created": created})
            return

        if self.path == "/api/sync_adspower":
            synced = STATE.sync_profiles_from_adspower_api()
            if synced > 0:
                STATE.add_log(f"[+] Đã đồng bộ {synced} Profile trực tiếp từ AdsPower Local API (127.0.0.1:50325).")
            self._send_json(200, {"ok": True, "synced": synced})
            return

        if self.path == "/api/sync_disk":
            STATE.sync_all_accounts_from_contactout_api()
            with STATE.lock:
                STATE.sync_all_accounts_from_disk()
                STATE.add_log("Đã đồng bộ lại dữ liệu tài khoản và sổ cái Credit.")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/update_acc":
            acc_id = data.get("accId")
            with STATE.lock:
                pref = STATE.user_prefs.get(acc_id, {})
                for a in STATE.accounts:
                    if a["id"] == acc_id:
                        if "enabled" in data:
                            a["enabled"] = bool(data["enabled"])
                            pref["enabled"] = bool(data["enabled"])
                        if "proxy" in data:
                            a["proxy"] = str(data["proxy"]).strip()
                            pref["proxy"] = str(data["proxy"]).strip()
                        if "adspowerId" in data:
                            a["adspowerId"] = str(data["adspowerId"]).strip()
                            pref["adspowerId"] = str(data["adspowerId"]).strip()
                        if "gmail" in data:
                            a["gmail"] = str(data["gmail"]).strip()
                            pref["gmail"] = str(data["gmail"]).strip()
                        if "credits" in data and isinstance(data["credits"], dict):
                            cur_cr = pref.get("credits") or dict(DEFAULT_SERVICE_CREDITS)
                            for k, v in data["credits"].items():
                                if k in DEFAULT_SERVICE_CREDITS:
                                    cur_cr[k] = max(0, int(v))
                            pref["credits"] = cur_cr
                            a["credits"] = dict(cur_cr)
                        break
                STATE.user_prefs[acc_id] = pref
                STATE.save_accounts()
                STATE.sync_all_accounts_from_disk()
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/add_acc":
            with STATE.lock:
                next_num = len(STATE.accounts) + 1
                new_id = f"acc_{next_num}"
                while any(a["id"] == new_id for a in STATE.accounts) or (PROFILES_DIR / new_id).exists():
                    next_num += 1
                    new_id = f"acc_{next_num}"
                (PROFILES_DIR / new_id).mkdir(parents=True, exist_ok=True)
                STATE.user_prefs[new_id] = {
                    "enabled": True,
                    "proxy": "",
                    "priority": next_num,
                    "adspowerId": "",
                    "gmail": f"gmail_{next_num:02d}@gmail.com",
                    "name": data.get("name") or f"AdsPower #{next_num:02d}",
                    "lastDailyReset": time.strftime("%Y-%m-%d"),
                    "credits": dict(DEFAULT_SERVICE_CREDITS),
                }
                STATE.save_accounts()
                STATE.sync_all_accounts_from_disk()
                STATE.add_log(f"Đã tạo Profile mới: {new_id}.")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/open_signalhire_rescue":
            li_url = (data.get("liUrl") or "").strip()
            if not li_url:
                self._send_json(400, {"error": "Thiếu URL ứng viên"})
                return
            with STATE.lock:
                candidate_acc = next(
                    (
                        a
                        for a in STATE.accounts
                        if a.get("enabled", True) and int((a.get("credits") or {}).get("signalhire", 0)) > 0
                    ),
                    None,
                )
                if not candidate_acc and STATE.accounts:
                    candidate_acc = STATE.accounts[0]
            if not candidate_acc:
                self._send_json(400, {"error": "Không tìm thấy Profile nào còn lượt SignalHire!"})
                return

            def _open_sh_rescue():
                STATE.manual_acc_id = candidate_acc["id"]
                STATE.add_log(
                    f"🎯 [SignalHire Cứu Nét] Mở [{candidate_acc['name']}] (còn {(candidate_acc.get('credits') or {}).get('signalhire', 10)} lượt SH) cho hồ sơ: {li_url}"
                )
                proc = launch_chrome_profile(candidate_acc, [li_url], engine_mode="manual")
                STATE.manual_proc = proc
                if proc is not None:
                    proc.wait()
                    kill_chrome_for_profile(proc, PROFILES_DIR / candidate_acc["id"])
                STATE.manual_proc = None
                STATE.manual_acc_id = None

            threading.Thread(target=_open_sh_rescue, daemon=True).start()
            self._send_json(200, {"ok": True, "accId": candidate_acc["id"]})
            return

        if self.path == "/api/open_acc":
            acc_id = data.get("accId")
            target = next((a for a in STATE.accounts if a["id"] == acc_id), None)
            if not target:
                self._send_json(400, {"error": "Không tìm thấy tài khoản"})
                return

            def _open_manual():
                STATE.manual_acc_id = target["id"]
                STATE.force_refresh_credits = True
                STATE.add_log(
                    f"Đang mở trình duyệt cho [{target['name']}] (nạp Argon_Collector + 6 Extension)."
                )
                proc = launch_chrome_profile(
                    target,
                    [
                        "https://www.linkedin.com/feed/",
                    ],
                    engine_mode="manual",
                )
                STATE.manual_proc = proc
                if proc is not None:
                    proc.wait()
                    kill_chrome_for_profile(proc, PROFILES_DIR / target["id"])
                STATE.manual_proc = None
                STATE.manual_acc_id = None
                STATE.sync_all_accounts_from_contactout_api()
                with STATE.lock:
                    STATE.sync_all_accounts_from_disk()
                STATE.add_log(f"Đã đóng và đồng bộ trạng thái cho [{target['name']}].")

            threading.Thread(target=_open_manual, daemon=True).start()
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/save_urls":
            with STATE.lock:
                STATE.save_raw_urls_text(data.get("rawUrls", ""))
                STATE.add_log(f"Đã lưu danh sách link ({len(STATE.pending_urls)} link cần lấy).")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/start_run":
            with STATE.lock:
                if STATE.is_running:
                    self._send_json(200, {"ok": True, "message": "Hệ thống đã đang chạy rồi!"})
                    return
                if "rawUrls" in data:
                    STATE.save_raw_urls_text(data["rawUrls"])
                if "quotaMode" in data:
                    STATE.quota_mode = data["quotaMode"]
                STATE.reload_urls_from_file(phase="multi")
                if len(STATE.pending_urls) == 0:
                    self._send_json(400, {"error": "Tất cả ứng viên trong danh sách đều đã được quét xong!"})
                    return
                STATE.is_running = True
                STATE.stop_requested = False

            threading.Thread(target=rotation_worker, daemon=True).start()
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/stop_run":
            with STATE.lock:
                STATE.stop_requested = True
                STATE.add_log("[!] Đã nhận lệnh dừng từ người dùng. Đang đóng phiên hiện tại...")
                if STATE.active_acc_id:
                    acc = next((a for a in STATE.accounts if a["id"] == STATE.active_acc_id), None)
                    if acc and acc.get("adspowerId"):
                        stop_adspower_profile(acc["adspowerId"])
                    elif STATE.active_proc:
                        kill_chrome_for_profile(STATE.active_proc, PROFILES_DIR / STATE.active_acc_id)
            STATE.reclaim_in_progress_url(reason="Người dùng bấm dừng")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/set_priority_acc":
            acc_id = data.get("accId")
            with STATE.lock:
                for a in STATE.accounts:
                    if a["id"] == acc_id:
                        a["priority"] = 1
                    else:
                        a["priority"] = max(2, a.get("priority", 2) + 1)
                STATE.accounts.sort(key=lambda a: (a.get("priority", 99), a["id"]))
                STATE.save_accounts()
                STATE.add_log(f"[*] Đã ưu tiên đặt [{acc_id}] chạy đầu tiên!")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/toggle_acc":
            acc_id = data.get("accId")
            en = data.get("enabled", True)
            with STATE.lock:
                for a in STATE.accounts:
                    if a["id"] == acc_id:
                        a["enabled"] = en
                        break
                STATE.save_accounts()
                STATE.add_log(f"[*] Đã {'bật' if en else 'tắt'} tài khoản [{acc_id}].")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/authwall":
            stuck = STATE.reclaim_in_progress_url(reason="LinkedIn Authwall")
            with STATE.lock:
                if stuck:
                    STATE.add_log(f"[!] LINKEDIN AUTHWALL: IP máy đang bị LinkedIn chặn khách trên link {stuck}!")
                    STATE.add_log("[!] Đã thu hồi link về hàng đợi an toàn. Hãy đổi IP (reset modem/phát 4G) hoặc thêm proxy vào accounts_config.json rồi chạy tiếp.")
                STATE.acc_exhausted = True
            self._send_json(200, {"ok": True})
            return

        if self.path == "/api/open_folder":
            try:
                if CSV_OUT.exists():
                    subprocess.Popen(f'explorer /select,"{CSV_OUT.resolve()}"')
                else:
                    os.startfile(str(BASE_DIR.resolve()))
            except Exception:
                pass
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not_found"})


def free_port(port: int) -> None:
    my_pid = os.getpid()
    ps_cmd = (
        f"Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" "
        f"| Where-Object {{ $_.ProcessId -ne {my_pid} -and ($_.CommandLine -like '*argon_server.py*' -or $_.CommandLine -like '*run_4_acc.py*') }} "
        f"| ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in res.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pid = int(parts[-1])
                    if pid > 0 and pid != my_pid:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
        time.sleep(0.4)
    except Exception:
        pass


def main() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    free_port(PORT)
    server = ThreadingHTTPServer((HOST, PORT), DashboardHTTPHandler)
    url = f"http://{HOST}:{PORT}"
    print("=" * 72)
    print(f" [Ritmada] ARGON 6-EXTENSION ORCHESTRATOR (20 ADSPOWER PROFILES): {url}")
    print(" -> Chay tuan tu 5 URL / Profile (Gop Mail Cong Ty + Mail Ca Nhan)")
    print(" -> Thac nuoc SDT: ContactOut -> Lusha -> Apollo (8cr) -> SignalHire (Bam tay)")
    print("=" * 72)

    def _auto_start_if_has_urls() -> None:
        time.sleep(1.2)
        with STATE.lock:
            if not STATE.is_running and STATE.pending_urls:
                STATE.is_running = True
                STATE.stop_requested = False
                STATE.add_log(f"[Auto-Start] Tự động bắt đầu với {len(STATE.pending_urls)} hồ sơ LinkedIn cần lấy.")
                threading.Thread(target=rotation_worker, daemon=True).start()

    threading.Thread(target=_auto_start_if_has_urls, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Đã tắt giao diện quản lý.")


if __name__ == "__main__":
    main()
