import pandas as pd
from lxml import etree
import re
import os
from datetime import datetime
from typing import List, Callable, Dict

def chinese_to_arabic(cn_num_str: str) -> str:
    """
    進階的中文數字轉阿拉伯數字函式，能處理'五百五十七'這樣的語意。
    """
    if not isinstance(cn_num_str, str): return cn_num_str
    
    cn_num_map = {'〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    cn_unit_map = {'十': 10, '百': 100, '千': 1000, '萬': 10000}
    
    # 直接替換，處理 "五十之三" -> "50之3"
    for cn, ar in cn_num_map.items():
        cn_num_str = cn_num_str.replace(cn, str(ar))
        
    # 處理進位
    if '十' in cn_num_str and cn_num_str.startswith('十'):
        cn_num_str = '1' + cn_num_str

    def _trans(s):
        num = 0
        if s:
            idx = s.find('十')
            if idx != -1:
                num += int(s[:idx]) * 10
                if len(s) > idx+1:
                    num += int(s[idx+1:])
            else:
                num += int(s)
        return num

    sec = cn_num_str.split('百')
    if len(sec) > 2: # 避免多個 "百"
        return cn_num_str

    num = 0
    if len(sec) == 2:
        if sec[0]:
            num += int(sec[0]) * 100
        else: #處理 "百三" -> 103
             num += 100
        num += _trans(sec[1])
    else:
        num = _trans(sec[0])
    return str(num)

def normalize_taiwan_address(address: str) -> Dict[str, str]:
    """對台灣地址進行深度正規化 (v2.8 最終版)。"""
    if not isinstance(address, str) or pd.isna(address) or not address.strip():
        return {'full': "", 'city': "", 'district': ""}
    
    addr = address.strip().upper().replace(" ", "").replace("\u3000", "").replace("臺", "台")
    addr = addr.replace('.', '、').replace('-', '之')
    full_width_nums = "０１２３４５６７８９"
    half_width_nums = "0123456789"
    addr = addr.translate(str.maketrans(full_width_nums, half_width_nums))
    addr = addr.replace('F', '樓')
    addr = re.sub(r'[\(（].*?[\)）]', '', addr)
    addr = re.sub(r'(\d+)鄰', '', addr)
    addr = re.sub(r'(縣|市|區|鄉|鎮|村|里|路|街|段|巷|弄|號|樓)\1+', r'\1', addr)

    addr = re.sub(r'([一二三四五六七八九十百]+)(?=段|巷|弄|號|樓|街)', lambda m: chinese_to_arabic(m.group(1)), addr)

    county_map = {"鹿港鎮": "彰化縣鹿港鎮", "彰化市": "彰化縣彰化市", "嘉義市": "嘉義縣嘉義市", "新竹市": "新竹縣新竹市"} # 簡化
    for city_short, city_full in county_map.items():
        if addr.startswith(city_short):
            addr = addr.replace(city_short, city_full, 1)
            break

    pattern = r'(?P<city>\D+?[縣市])?(?P<district>\D+?[區鄉鎮市])?(?P<village>\D+?[村里])?(?P<road>.*?((路|街|大道|道)(?!.*(路|街|大道|道))))?(?P<section>\d+[段])?(?P<lane>\d+[巷])?(?P<alley>\d+[弄])?(?P<number>[\d之、-]+[號])?(?P<floor>\d+[樓])?(?P<rest>.*)'
    match = re.search(pattern, addr)
    if not match: return {'full': addr, 'city': "", 'district': ""}
    parts = match.groupdict(default='')
    
    # --- 【核心修正】擴充權威性判斷規則 ---
    village_part = parts.get('village', '')
    # 如果地址中包含路/街/段，或「巷」，則村里為贅述，應忽略
    if parts.get('road') or parts.get('section') or parts.get('lane'):
        village_part = ''
        
    normalized_full = f"{parts.get('city', '')}{parts.get('district', '')}{village_part}{parts.get('road', '')}{parts.get('section', '')}{parts.get('lane', '')}{parts.get('alley', '')}{parts.get('number', '')}{parts.get('floor', '')}{parts.get('rest', '')}"
    normalized_full = re.sub(r'\s+', '', normalized_full).strip()
    
    return {'full': normalized_full, 'city': parts.get('city', ''), 'district': parts.get('district', '')}

def parse_and_process_reports(file_paths: List[str], log_callback: Callable[[str], None]) -> pd.DataFrame:
    """
    解析所有下載的XML報表檔案，進行清理、正規化。
    """
    log_callback("INFO: 開始執行報表解析與資料處理程序...")
    all_dataframes = []
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}

    for file_path in file_paths:
        try:
            tree = etree.parse(file_path)
            rows_xml = tree.xpath('.//ss:Row', namespaces=ns)
            header, all_rows_data, is_data_section = [], [], False
            for row in rows_xml:
                cells_text = [(data.text or "").strip() for cell in row.findall('ss:Cell', ns) for data in cell.findall('ss:Data', ns)]
                if not cells_text: continue
                if cells_text[0] == "入境日" and not is_data_section:
                    is_data_section = True
                    header = [h.replace('\n', '') for h in cells_text]
                    continue
                if is_data_section:
                    row_data = cells_text[:len(header)]
                    while len(row_data) < len(header):
                        row_data.append("")
                    all_rows_data.append(row_data)
            if header and all_rows_data:
                df = pd.DataFrame(all_rows_data, columns=header)
                all_dataframes.append(df)
        except Exception as e:
            log_callback(f"ERROR: 解析檔案 {os.path.basename(file_path)} 時發生錯誤: {e}")

    if not all_dataframes:
        log_callback("CRITICAL: 所有檔案均解析失敗或為空。")
        return pd.DataFrame()

    master_df = pd.concat(all_dataframes, ignore_index=True)
    log_callback(f"INFO: 所有報表已成功合併！總共有 {len(master_df)} 筆原始資料。")

    if not master_df.empty and str(master_df.iloc[-1, 0]).strip().startswith('合計'):
        master_df = master_df.iloc[:-1]
        log_callback("INFO: 已成功移除合計列。")
    
    log_callback("INFO: 正在過濾無效的空白資料列...")
    original_rows = len(master_df)
    master_df.dropna(subset=['雇主簡稱', '中文譯名'], inplace=True)
    master_df = master_df[master_df['雇主簡稱'].str.strip() != '']
    master_df = master_df[master_df['中文譯名'].str.strip() != '']
    log_callback(f"INFO: 已過濾 {original_rows - len(master_df)} 筆無效資料列。")

    log_callback("INFO: 正在進行資料欄位標準化與正規化...")
    column_mapping = {
        '雇主簡稱': 'employer_name', '中文譯名': 'worker_name', '性別': 'gender',
        '國籍': 'nationality', '護照號碼': 'passport_number', '居留證號': 'arc_number',
        '入境日': 'arrival_date', '離境日': 'departure_date', '工作期限': 'work_permit_expiry_date',
        '居留地址': 'original_address',
    }
    master_df.rename(columns=column_mapping, inplace=True)

    log_callback("INFO: 正在強制統一所有日期欄位格式為 YYYY-MM-DD...")
    date_columns = ['arrival_date', 'departure_date', 'work_permit_expiry_date']
    for col in date_columns:
        if col in master_df.columns:
            # errors='coerce' 會將無法解析的日期變為 NaT (空值)，確保程式不會崩潰
            master_df[col] = pd.to_datetime(master_df[col], errors='coerce').dt.strftime('%Y-%m-%d')
            # 將 pandas 的 <NaT> 空值轉換為 Python 的 None
            master_df[col] = master_df[col].where(pd.notna(master_df[col]), None)

    regex_pattern = r'\s?\(接\)$|\s?\(遞:.*?\)$'
    master_df['employer_name'] = master_df['employer_name'].str.replace(regex_pattern, '', regex=True).str.strip()
    
    master_df['unique_id'] = master_df['employer_name'].astype(str).str.strip() + '_' + master_df['worker_name'].astype(str).str.strip()
    
    addr_info = master_df['original_address'].apply(normalize_taiwan_address).apply(pd.Series)
    master_df[['normalized_address', 'city', 'district']] = addr_info[['full', 'city', 'district']]
    
    final_columns = [
        'unique_id', 'employer_name', 'worker_name', 'gender', 'nationality', 
        'passport_number', 'arc_number', 'arrival_date', 'departure_date', 
        'work_permit_expiry_date', 'original_address', 'normalized_address', 'city', 'district'
    ]
    existing_final_columns = [col for col in final_columns if col in master_df.columns]
    final_df = master_df[existing_final_columns].drop_duplicates(subset=['unique_id'], keep='first').copy()
    
    log_callback(f"INFO: 資料清理與正規化完成，最終處理完畢資料共 {len(final_df)} 筆。")
    return final_df