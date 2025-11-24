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
    addr = addr.replace('鎭', '鎮')
    addr = addr.replace('F', '樓')
    addr = re.sub(r'[\(（].*?[\)）]', '', addr)
    addr = re.sub(r'(\d+)鄰', '', addr)
    addr = re.sub(r'(縣|市|區|鄉|鎮|村|里|路|街|段|巷|弄|號|樓)\1+', r'\1', addr)

    addr = re.sub(r'([一二三四五六七八九十百]+)(?=段|巷|弄|號|樓|街)', lambda m: chinese_to_arabic(m.group(1)), addr)

    county_map = {
        # 彰化縣 (2市 6鎮 18鄉)
        "彰化市": "彰化縣彰化市",
        "員林市": "彰化縣員林市",
        "和美鎮": "彰化縣和美鎮",
        "鹿港鎮": "彰化縣鹿港鎮",
        "溪湖鎮": "彰化縣溪湖鎮",
        "二林鎮": "彰化縣二林鎮",
        "田中鎮": "彰化縣田中鎮",
        "北斗鎮": "彰化縣北斗鎮",
        "花壇鄉": "彰化縣花壇鄉",
        "芬園鄉": "彰化縣芬園鄉",
        "大村鄉": "彰化縣大村鄉",
        "永靖鄉": "彰化縣永靖鄉",
        "伸港鄉": "彰化縣伸港鄉",
        "線西鄉": "彰化縣線西鄉",
        "福興鄉": "彰化縣福興鄉",
        "秀水鄉": "彰化縣秀水鄉",
        "埔心鄉": "彰化縣埔心鄉",
        "埔鹽鄉": "彰化縣埔鹽鄉",
        "大城鄉": "彰化縣大城鄉",
        "芳苑鄉": "彰化縣芳苑鄉",
        "竹塘鄉": "彰化縣竹塘鄉",
        "社頭鄉": "彰化縣社頭鄉",
        "二水鄉": "彰化縣二水鄉",
        "田尾鄉": "彰化縣田尾鄉",
        "埤頭鄉": "彰化縣埤頭鄉",
        "溪州鄉": "彰化縣溪州鄉",

        # 雲林縣 (1市 5鎮 14鄉)
        "斗六市": "雲林縣斗六市",
        "斗南鎮": "雲林縣斗南鎮",
        "虎尾鎮": "雲林縣虎尾鎮",
        "西螺鎮": "雲林縣西螺鎮",
        "土庫鎮": "雲林縣土庫鎮",
        "北港鎮": "雲林縣北港鎮",
        "莿桐鄉": "雲林縣莿桐鄉",
        "林內鄉": "雲林縣林內鄉",
        "古坑鄉": "雲林縣古坑鄉",
        "大埤鄉": "雲林縣大埤鄉",
        "崙背鄉": "雲林縣崙背鄉",
        "二崙鄉": "雲林縣二崙鄉",
        "麥寮鄉": "雲林縣麥寮鄉",
        "東勢鄉": "雲林縣東勢鄉",
        "褒忠鄉": "雲林縣褒忠鄉",
        "臺西鄉": "雲林縣臺西鄉",
        "元長鄉": "雲林縣元長鄉",
        "四湖鄉": "雲林縣四湖鄉",
        "口湖鄉": "雲林縣口湖鄉",
        "水林鄉": "雲林縣水林鄉",

        # 嘉義縣 (2市 3鎮 15鄉)
        "太保市": "嘉義縣太保市",
        "朴子市": "嘉義縣朴子市",
        "布袋鎮": "嘉義縣布袋鎮",
        "大林鎮": "嘉義縣大林鎮",
        "民雄鄉": "嘉義縣民雄鄉",
        "溪口鄉": "嘉義縣溪口鄉",
        "新港鄉": "嘉義縣新港鄉",
        "六腳鄉": "嘉義縣六腳鄉",
        "東石鄉": "嘉義縣東石鄉",
        "義竹鄉": "嘉義縣義竹鄉",
        "鹿草鄉": "嘉義縣鹿草鄉",
        "水上鄉": "嘉義縣水上鄉",
        "中埔鄉": "嘉義縣中埔鄉",
        "竹崎鄉": "嘉義縣竹崎鄉",
        "梅山鄉": "嘉義縣梅山鄉",
        "番路鄉": "嘉義縣番路鄉",
        "大埔鄉": "嘉義縣大埔鄉",
        "阿里山鄉": "嘉義縣阿里山鄉",

        # 嘉義市 (直轄市)
        "嘉義市": "嘉義市嘉義市",

        # 新竹縣 (1市 3鎮 9鄉)
        "竹北市": "新竹縣竹北市",
        "竹東鎮": "新竹縣竹東鎮",
        "新埔鎮": "新竹縣新埔鎮",
        "關西鎮": "新竹縣關西鎮",
        "湖口鄉": "新竹縣湖口鄉",
        "新豐鄉": "新竹縣新豐鄉",
        "芎林鄉": "新竹縣芎林鄉",
        "橫山鄉": "新竹縣橫山鄉",
        "北埔鄉": "新竹縣北埔鄉",
        "寶山鄉": "新竹縣寶山鄉",
        "峨眉鄉": "新竹縣峨眉鄉",
        "尖石鄉": "新竹縣尖石鄉",
        "五峰鄉": "新竹縣五峰鄉",

        # 新竹市 (直轄市)
        "新竹市": "新竹市新竹市",
    }

    for city_short, city_full in county_map.items():
        if addr.startswith(city_short):
            addr = addr.replace(city_short, city_full, 1)
            break
    pattern = r'(?P<city>\D+?[縣市])?(?P<district>\D+?[區鄉鎮市])?(?P<village>\D+?[村里])?(?P<road>.*?((路|街|大道|道)(?!.*(路|街|大道|道))))?(?P<section>.*?[段])?(?P<lane>.*?[巷])?(?P<alley>.*?[弄])?(?P<number>[\d之、-]+[號])?(?P<floor>.*?[樓])?(?P<rest>.*)'
    match = re.search(pattern, addr)
    if not match: return {'full': addr, 'city': "", 'district': ""}
    parts = match.groupdict(default='')
    
    # --- 擴充權威性判斷規則 ---
    village_part = parts.get('village', '')
    # 如果地址中包含路/街/段，或「巷」，則村里為贅述，應忽略
    if parts.get('road') or parts.get('section') or parts.get('lane'):
        village_part = ''
        
    normalized_full = f"{parts.get('city', '')}{parts.get('district', '')}{village_part}{parts.get('road', '')}{parts.get('section', '')}{parts.get('lane', '')}{parts.get('alley', '')}{parts.get('number', '')}{parts.get('floor', '')}{parts.get('rest', '')}"
    normalized_full = re.sub(r'\s+', '', normalized_full).strip()
    
    return {'full': normalized_full, 'city': parts.get('city', ''), 'district': parts.get('district', '')}

def parse_and_process_reports(
    file_paths: List[str],
    log_callback: Callable[[str], None]
) -> pd.DataFrame:
    """
    【v2.19 "日誌增強" 修正版】
    在過濾掉缺少必要欄位的資料列時，印出明確的警告日誌，
    讓使用者能追蹤是哪個檔案的哪筆資料被跳過了。
    """
    log_callback("INFO: 開始執行報表解析與資料處理程序 (v2.19 日誌增強版)...")
    all_workers_data = [] # 儲存 {欄位名: 值} 的字典列表
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
    parser = etree.XMLParser(recover=True, encoding='utf-8')

    # 1. 定義我們系統真正需要的欄位
    REQUIRED_COLS_MAP = {
        '客戶簡稱': 'employer_name',
        '姓名(中)': 'worker_name',
        '英文姓名': 'native_name',
        '性別': 'gender',
        '國籍': 'nationality',
        '護照號碼': 'passport_number',
        '居留證號': 'arc_number',
        '交工日': 'accommodation_start_date',
        '聘僱期滿日': 'work_permit_expiry_date',
        '居住地址': 'original_address',
        '出境日期': 'departure_date'
    }
    
    for file_path in file_paths:
        header_index_map = {}
        is_data_section = False
        
        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            if not file_content:
                log_callback(f"WARNING: 檔案 {os.path.basename(file_path)} 內容為空，已略過。")
                continue

            tree = etree.fromstring(file_content, parser=parser)
            rows_xml = tree.xpath('.//ss:Row', namespaces=ns)
            
            # log_callback(f"INFO: 正在解析檔案: {os.path.basename(file_path)}...")
            
            for row in rows_xml:
                
                cells_text = []
                for cell in row.findall('ss:Cell', ns):
                    data_element = cell.find('ss:Data', ns)
                    if data_element is not None and data_element.text is not None:
                        cells_text.append(data_element.text.strip())
                    else:
                        cells_text.append("") 
                
                if not cells_text: continue
                
                if "客戶簡稱" in cells_text and "姓名(中)" in cells_text and not is_data_section:
                    is_data_section = True
                    # log_callback(f"INFO: 在檔案 {os.path.basename(file_path)} 中找到資料標頭，正在建立欄位索引...")
                     
                    header_index_map = {}
                    for i, col_name in enumerate(cells_text):
                        if col_name in REQUIRED_COLS_MAP:
                            if col_name not in header_index_map: 
                                header_index_map[col_name] = i
                    
                    missing_cols = set(REQUIRED_COLS_MAP.keys()) - set(header_index_map.keys())
                    if missing_cols:
                        log_callback(f"CRITICAL: 檔案 {os.path.basename(file_path)} 的標頭中缺少必要欄位: {missing_cols}。跳過此檔案。")
                        is_data_section = False
                        header_index_map = {}
                        break 
                    
                    # log_callback(f"INFO: 欄位索引建立成功。 '居住地址' 位於索引 {header_index_map.get('居住地址', 'N/A')}, '交工日' 位於索引 {header_index_map.get('交工日', 'N/A')}。")
                    continue 

                if is_data_section:
                    worker_dict = {}
                    try:
                        for xml_col_name, internal_col_name in REQUIRED_COLS_MAP.items():
                            col_index = header_index_map[xml_col_name]
                            if col_index < len(cells_text):
                                worker_dict[internal_col_name] = cells_text[col_index]
                            else:
                                worker_dict[internal_col_name] = ""
                        
                        # 基礎驗證，並在失敗時印出日誌
                        emp_name = worker_dict.get('employer_name')
                        w_name = worker_dict.get('worker_name')
                        addr = worker_dict.get('original_address') # "居住地址"

                        if not emp_name or not w_name or not addr:
                            # 新增日誌，讓被跳過的資料不再是 "安靜" 的
                            log_callback(f"WARNING: [資料過濾] 在檔案 {os.path.basename(file_path)} 中跳過一筆資料，因缺少必要欄位。 (雇主: '{emp_name}', 姓名: '{w_name}', 居住地址: '{addr}')")
                            continue # 跳過缺少雇主、姓名、或居住地址的資料

                        all_workers_data.append(worker_dict)
                    
                    except IndexError:
                        log_callback(f"WARNING: 偵測到資料列長度不足或格式不符，已跳過。")
                    except Exception as e:
                         log_callback(f"WARNING: 解析資料列時出錯: {e}")

        except Exception as e:
            log_callback(f"ERROR: 解析檔案 {os.path.basename(file_path)} 時發生嚴重錯誤: {e}")

    if not all_workers_data:
        log_callback("CRITICAL: 所有檔案均解析失敗或為空，未抓取到任何有效資料。")
        return pd.DataFrame()

    master_df = pd.DataFrame(all_workers_data)
    log_callback(f"INFO: 所有報表已成功合併！總共有 {len(master_df)} 筆有效資料。")

    log_callback("INFO: 正在過濾地址 (居住地址) 為空的資料列...")
    original_rows = len(master_df)
    master_df = master_df.loc[master_df['original_address'].notna() & (master_df['original_address'].str.strip() != '')].copy()
    log_callback(f"INFO: 已過濾 {original_rows - len(master_df)} 筆地址為空的資料列。")

    log_callback("INFO: 正在強制統一所有日期欄位格式為 YYYY-MM-DD...")
    date_columns = ['accommodation_start_date', 'work_permit_expiry_date', 'departure_date']
    
    def robust_date_converter(x):
        if pd.isna(x) or str(x).strip() == "":
            return None
        dt = pd.to_datetime(x, errors='coerce')
        if pd.isna(dt):
            log_callback(f"WARNING: 發現無效日期格式 '{x}'，將其設定為 NULL。")
            return None
        return dt.strftime('%Y-%m-%d')

    for col in date_columns:
        if col in master_df.columns:
            master_df[col] = master_df[col].apply(robust_date_converter)

    regex_pattern = r'\s?\(接\)$|\s?\(遞:.*?\)$'
    master_df['employer_name'] = master_df['employer_name'].str.replace(regex_pattern, '', regex=True).str.strip()
    
    log_callback("INFO: 正在根據最新規則生成 Unique ID...")
    def generate_unique_id(row):
        employer = str(row.get('employer_name', '')).strip()
        name = str(row.get('worker_name', '')).strip()
        passport = str(row.get('passport_number', '')).strip()
        
        if passport:
            return f"{employer}_{name}_{passport}"
        else:
            return f"{employer}_{name}"

    master_df['unique_id'] = master_df.apply(generate_unique_id, axis=1)

    addr_info = master_df['original_address'].apply(normalize_taiwan_address).apply(pd.Series)
    master_df[['normalized_address', 'city', 'district']] = addr_info[['full', 'city', 'district']]
    
    final_columns = [
        'unique_id', 'employer_name', 'worker_name', 'native_name', 'gender', 'nationality', 
        'passport_number', 'arc_number', 
        'accommodation_start_date',
        'work_permit_expiry_date', 
        'departure_date', 
        'original_address', 'normalized_address', 'city', 'district'
    ]
    existing_final_columns = [col for col in final_columns if col in master_df.columns]
    
    final_df = master_df[master_df['unique_id'] != '_'].copy()
    final_df = final_df[existing_final_columns].drop_duplicates(subset=['unique_id'], keep='first')
    
    log_callback(f"INFO: 資料清理與正規化完成，最終處理完畢資料共 {len(final_df)} 筆。")
    return final_df

def parse_b04_xml(file_path_or_buffer, fee_mapping: dict) -> pd.DataFrame:
    """
    解析 B04 應收帳款 XML 報表 (Excel 2003 XML 格式)。
    【v2.1 索引修正版】修復空儲存格導致欄位位移的問題。
    """
    try:
        if hasattr(file_path_or_buffer, 'read'):
            xml_content = file_path_or_buffer.read()
        else:
            with open(file_path_or_buffer, 'rb') as f:
                xml_content = f.read()

        parser = etree.XMLParser(recover=True, encoding='utf-8')
        tree = etree.fromstring(xml_content, parser=parser)
        
        ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        rows = tree.xpath('.//ss:Row', namespaces=ns)
        
        extracted_data = []
        
        # 欄位索引
        IDX_EMPLOYER = 2
        IDX_WORKER = 4
        IDX_PASSPORT = 5
        IDX_FEE_NAME = 8
        IDX_BILL_DATE = 9
        IDX_AMOUNT = 10

        for row in rows:
            cells = row.findall('ss:Cell', ns)
            cell_texts = {}
            
            # --- 【核心修正】使用獨立變數追蹤欄位索引 ---
            next_col_idx = 0 
            
            for cell in cells:
                # 檢查是否有指定 Index (Excel XML 跳過空值時會用這個屬性)
                idx_attr = cell.get(f"{{{ns['ss']}}}Index")
                if idx_attr:
                    next_col_idx = int(idx_attr) - 1
                
                current_idx = next_col_idx
                
                data = cell.find('ss:Data', ns)
                if data is not None and data.text:
                    cell_texts[current_idx] = data.text.strip()
                
                # 準備下一個欄位索引 (預設+1)
                next_col_idx += 1
            # -------------------------------------------

            # 檢查是否為數據列
            seq_no = cell_texts.get(0)
            if not seq_no or not seq_no.isdigit():
                continue

            # 提取費用名稱
            fee_name = cell_texts.get(IDX_FEE_NAME)
            if fee_name not in fee_mapping:
                continue

            # 日期轉換
            roc_date_str = cell_texts.get(IDX_BILL_DATE)
            effective_date = None
            if roc_date_str:
                try:
                    parts = roc_date_str.split('/')
                    if len(parts) == 3:
                        year = int(parts[0]) + 1911
                        effective_date = f"{year}-{parts[1]}-{parts[2]}"
                except:
                    pass
            if not effective_date: continue

            # 金額轉換
            amount_str = cell_texts.get(IDX_AMOUNT)
            try:
                amount = int(float(amount_str)) if amount_str else 0
            except:
                amount = 0

            # 姓名清理
            raw_worker_name = cell_texts.get(IDX_WORKER, "")
            clean_worker_name = re.sub(r'\s*[（\(].*?[）\)]', '', raw_worker_name).strip()
            
            raw_emp_name = cell_texts.get(IDX_EMPLOYER, "")
            clean_emp_name = re.sub(r'\s*[（\(].*?[）\)]', '', raw_emp_name).strip()

            # 護照號碼 (若沒抓到就是 None)
            passport = cell_texts.get(IDX_PASSPORT)

            extracted_data.append({
                'employer_name': clean_emp_name,
                'worker_name': clean_worker_name,
                'passport_number': passport, # 允許為 None
                'fee_type': fee_mapping[fee_name],
                'source_fee_name': fee_name,
                'amount': amount,
                'effective_date': effective_date
            })

        return pd.DataFrame(extracted_data)

    except Exception as e:
        print(f"解析 XML 失敗: {e}")
        return pd.DataFrame()