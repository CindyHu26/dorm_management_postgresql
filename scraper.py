import concurrent.futures
import os
import shutil
import string
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

import requests


DEFAULT_MAX_WORKERS = 8
REQUEST_TIMEOUT_SECONDS = 300


def generate_code_ranges() -> List[Tuple[str, str]]:
    """
    Generate all employer code ranges used by the legacy export.
    Examples: A01-A01-S, A02-A02-S, ..., AA-AA-S, ..., ZZ-ZZ-S.
    """
    ranges: List[Tuple[str, str]] = []
    letters = string.ascii_uppercase

    for prefix in 'ABCDEFGH':
        for start in range(1, 100):
            start_code = f"{prefix}{start:02d}"
            ranges.append((start_code, f"{start_code}-S"))

    for a in letters:
        for b in letters:
            start_code = f"{a}{b}"
            ranges.append((start_code, f"{start_code}-S"))

    return ranges


def download_all_reports(
    target_url: str,
    auth_credentials: Tuple[str, str],
    query_ranges: List[Tuple[str, str]],
    temp_dir: str,
    log_callback: Callable[[str], None],
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> List[str]:
    """
    Download all range-based XLS reports from the legacy system.
    Requests are sent in parallel with a bounded worker count to reduce total runtime.
    """
    log_callback("INFO: 開始批次下載報表 (平行請求模式)...")

    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir)
        log_callback(f"INFO: 已清空並建立暫存資料夾 {temp_dir}")
    except OSError as e:
        log_callback(f"CRITICAL: 無法準備暫存資料夾 {temp_dir}: {e}")
        return []

    total_ranges = len(query_ranges)
    if total_ranges == 0:
        log_callback("WARNING: 沒有可下載的查詢區間。")
        return []

    worker_count = max(1, min(max_workers, total_ranges))
    base_date_str = datetime.today().strftime('%Y-%m-%d')

    log_callback(f"INFO: 基準日期 {base_date_str}，總區間數 {total_ranges}，workers={worker_count}")

    def download_single_range(index: int, start_code: str, end_code: str) -> Optional[str]:
        # --- 【核心修改 2】更新 payload ---
        payload = {
            'CU00_BNO1': start_code,         # 起始雇主編號
            'CU00_ENO1': end_code,           # 截止雇主編號
            'CU00_SDATE': '2',              # 期間別: 2 (接管日)
            'CU00_BDATE': '',               # 期間...起始日 (依需求留空)
            'CU00_EDATE': '',               # 期間...截止日 (依需求留空)
            'CU00_BDATE1': '',              # 空白
            'CU00_EDATE1': '',              # 空白
            'CU00_BDATE2': '',              # 空白
            'CU00_EDATE2': '',              # 空白
            'CU00_BASE': base_date_str,     # 基準日期 (依需求改為今日)
            'CU00_BASE_I': 'Y',             # 廢止聘可移工算任用中?: Y
            'CU00_LA04': '0',               # 接管身份代號: 所有
            'CU00_LA19': '0',               # 離管身份代號: 所有
            'CU00_LA198': '0',              # 申請類別: 全部
            'CU00_ORG1': 'A',               # 任用來源: 全部
            'CU00_WORK': '0',               
            'CU00_PNO': '0',                # 移工類別: 全部 (依需求確認為 '0')
            'CU00_LA28': '0',               # 外勞國籍: 全部
            'CU00_SALERS': 'A',             # 業務人員: 全部
            'CU00_MEMBER': 'A',             # 負責行政人員: 全部
            'CU00_SERVS': 'A',              # 負責客服人員: 全部 
            'CU00_ACCS': '0',               # 負責會計人員: 全部
            'CU00_TRANSF': 'A',             # 負責雙語人員: 全部
            'CU00_RET': '0',                # 所屬縣市: 全部
            'CU00_ORD': '1',                # 資料排序: 日期
            'CU00_chk1': 'N',               # 不同雇主是否跳頁: N
            'CU00_chk2': 'N',               # 不同業務是否跳頁: N 
            'CU00_chk21': 'D',              # 報表格式: D
            'CU00_SEL35': '2',              # 表單日期格式: 2 (西元)
            'CU00_LA120': '全部',                 # 國內仲介: 全部 (對應的欄位是空的)
            'key': '轉出Excel'
        }

        try:
            response = requests.post(
                target_url,
                data=payload,
                auth=auth_credentials,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

            if 'text/html' in response.headers.get('content-type', '').lower():
                log_callback(
                    f"WARNING: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} 回傳 HTML，略過。"
                )
                return None

            file_path = os.path.join(temp_dir, f"report_{start_code}_to_{end_code}.xls")
            with open(file_path, 'wb') as f:
                f.write(response.content)
            return file_path
        except requests.exceptions.Timeout:
            log_callback(
                f"ERROR: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} 請求逾時。"
            )
        except requests.exceptions.RequestException as e:
            log_callback(
                f"ERROR: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} HTTP 請求失敗: {e}"
            )
        except Exception as e:
            log_callback(
                f"ERROR: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} 發生未預期錯誤: {e}"
            )
        return None

    completed_files: Dict[int, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(download_single_range, index, start_code, end_code): (index, start_code, end_code)
            for index, (start_code, end_code) in enumerate(query_ranges)
        }

        for future in concurrent.futures.as_completed(future_map):
            index, start_code, end_code = future_map[future]
            try:
                file_path = future.result()
                if file_path:
                    completed_files[index] = file_path
                    log_callback(
                        f"SUCCESS: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} 下載完成。"
                    )
            except Exception as e:
                log_callback(
                    f"ERROR: 區間 {index + 1}/{total_ranges} {start_code}-{end_code} 執行緒處理失敗: {e}"
                )

    downloaded_files = [completed_files[index] for index in sorted(completed_files)]

    if not downloaded_files:
        log_callback("WARNING: 本次沒有成功下載任何報表。")
    else:
        log_callback(f"INFO: 批次下載完成，共成功下載 {len(downloaded_files)} 份報表。")

    return downloaded_files
