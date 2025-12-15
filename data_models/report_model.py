import pandas as pd
import database
from datetime import datetime, date
import json
import os

def get_fee_config():
    """讀取費用設定檔，用於獲取自訂的費用排序 (與 finance_model 共用邏輯)。"""
    config_file = "fee_config.json"
    default_config = {
        "internal_types": ["房租", "水電費", "清潔費", "宿舍復歸費", "充電清潔費", "充電費"],
        "mapping": {}
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default_config
    return default_config

def _execute_query_to_dataframe(conn, query, params=None):
    """一個輔助函式，用來手動執行查詢並回傳 DataFrame。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_dorm_report_data(dorm_id: int, year_month: str):
    """
    【v3.4 費用區間修正版】查詢宿舍在指定月份的住宿人員詳細資料。
    修正：費用欄位「嚴格」只抓取該月份 (當月1號~當月月底) 的紀錄。
         若該員工當月無費用，則顯示 0，不再回溯抓取舊資料。
    """
    if not dorm_id: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
        
    try:
        # 1. SQL 查詢
        query = """
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as month_start,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as month_end
            ),
            -- 【核心修正】只抓取「該月份」的費用，不回溯
            TargetMonthFees AS (
                SELECT
                    fh.worker_unique_id, 
                    fh.fee_type, 
                    SUM(fh.amount) as amount -- 若同月有多筆(如補扣)，將其加總
                FROM "FeeHistory" fh
                CROSS JOIN DateParams dp
                WHERE fh.effective_date BETWEEN dp.month_start AND dp.month_end
                GROUP BY fh.worker_unique_id, fh.fee_type
            )
            SELECT
                r.room_number AS "房號",
                w.worker_name AS "姓名",
                w.employer_name AS "雇主",
                w.gender AS "性別",
                w.nationality AS "國籍",
                w.special_status AS "特殊狀況",
                w.worker_notes AS "備註",
                
                -- 費用資料 (若無當月紀錄則為 NULL)
                tmf.fee_type,
                tmf.amount
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            CROSS JOIN DateParams dp
            
            -- 關聯費用 (使用新的 TargetMonthFees)
            LEFT JOIN TargetMonthFees tmf ON w.unique_id = tmf.worker_unique_id
            
            WHERE r.dorm_id = %(dorm_id)s
            -- 住宿期間與查詢月份有重疊
            AND ah.start_date <= dp.month_end
            AND (ah.end_date IS NULL OR ah.end_date >= dp.month_start)
            
            ORDER BY r.room_number, w.worker_name
        """
        
        params = {"dorm_id": dorm_id, "year_month": year_month}
        raw_df = _execute_query_to_dataframe(conn, query, params)
        
        if raw_df.empty:
            return pd.DataFrame()

        # 2. 資料處理與轉置 (Pivot)
        raw_df['fee_type'] = raw_df['fee_type'].fillna('__NO_FEE__')
        raw_df['amount'] = raw_df['amount'].fillna(0)
        
        # 填補基本資料空值
        fill_values = {
            "房號": "", "姓名": "", "雇主": "", 
            "性別": "", "國籍": "", 
            "特殊狀況": "", "備註": ""
        }
        raw_df = raw_df.fillna(value=fill_values)
        
        index_cols = ["房號", "姓名", "雇主", "性別", "國籍", "特殊狀況", "備註"]
        
        pivot_df = raw_df.pivot_table(
            index=index_cols,
            columns='fee_type',
            values='amount',
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        
        if '__NO_FEE__' in pivot_df.columns:
            pivot_df.drop(columns=['__NO_FEE__'], inplace=True)
            
        # 3. 排序與加總
        fee_cols = [c for c in pivot_df.columns if c not in index_cols]
        config = get_fee_config()
        ordered_types = config.get("internal_types", [])
        
        def sort_key(col_name):
            if col_name in ordered_types: return ordered_types.index(col_name)
            return 999

        fee_cols = sorted(fee_cols, key=sort_key)
        pivot_df['總收租'] = pivot_df[fee_cols].sum(axis=1)
        
        final_cols = index_cols + fee_cols + ['總收租']
        return pivot_df[final_cols]
        
    except Exception as e:
        print(f"查詢宿舍報表資料時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_monthly_exception_report(year_month: str):
    """
    【v2.0 修改版】查詢指定月份中，所有「當月離住」或「有特殊狀況」的人員。
    """
    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
        
    try:
        query = """
            -- 查詢一：找出所有在該月份『最終離住』的人員 (邏輯不變)
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                '當月離住' AS "備註"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id 
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE TO_CHAR(w.accommodation_end_date, 'YYYY-MM') = %s

            UNION ALL

            -- 查詢二：找出所有在該月份有特殊狀況的『在住』人員
            SELECT
                d.original_address AS "宿舍地址",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.accommodation_start_date AS "起住日",
                w.accommodation_end_date AS "離住日",
                w.special_status AS "備註"
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE
                ah.start_date < (TO_DATE(%s, 'YYYY-MM') + '1 month'::interval)
                AND (ah.end_date IS NULL OR ah.end_date >= TO_DATE(%s, 'YYYY-MM'))
                AND w.special_status IS NOT NULL
                AND w.special_status != ''
                AND w.special_status != '在住'
            ORDER BY "宿舍地址", "姓名"
        """
        
        first_day_of_month_str = f"{year_month}-01"
        params = (year_month, first_day_of_month_str, first_day_of_month_str)
        
        return _execute_query_to_dataframe(conn, query, params)
        
    except Exception as e:
        print(f"查詢月份異動人員報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: 
            conn.close()

def get_utility_bills_for_selection(dorm_ids, start_date, end_date):
    """
    獲取指定宿舍列表和日期範圍內的水費和電費帳單。
    """
    if not dorm_ids: return []
    
    conn = database.get_db_connection()
    if not conn: return []
    
    try:
        # 【修正】檢查輸入類型：如果是單一整數，將其轉換為列表
        if isinstance(dorm_ids, int):
            target_ids = [dorm_ids]
        else:
            target_ids = dorm_ids

        # 確保列表中的元素都是整數，並維持 List 型態 (給 ANY 使用)
        safe_dorm_ids = list(int(i) for i in target_ids)
        
        query = """
            SELECT
                id, dorm_id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE 
                dorm_id = ANY(%s) 
                AND (bill_type = '水費' OR bill_type = '電費')
                AND bill_end_date >= %s
                AND bill_start_date <= %s
            ORDER BY dorm_id, bill_type, bill_end_date DESC;
        """
        # 注意：safe_dorm_ids 本身是 list，但在 execute 參數中要放在 tuple 裡
        df = _execute_query_to_dataframe(conn, query, (safe_dorm_ids, start_date, end_date))
        return df.to_dict('records')
        
    except Exception as e:
        print(f"Error getting utility bills for selection: {e}")
        return []
    finally:
        if conn: conn.close()

def get_custom_utility_report_data(dorm_id: int, employer_name: str, selected_bill_ids: list):
    """
    【v2.3 完整歷史修正版】根據使用者選擇的帳單 ID，產生客製化水電費分攤報表。
    邏輯修正：解決「帳單截止後才換床」導致被誤判為離住的問題。
    方法：先篩選出期間內有居住的人員，再撈取這些人在該宿舍的「所有」歷史紀錄來判斷狀態。
    """
    conn = database.get_db_connection()
    if not conn or not selected_bill_ids:
        return None, None, None

    try:
        from datetime import date, timedelta # 確保引入時間計算模組

        dorm_details = _execute_query_to_dataframe(conn, 'SELECT original_address, dorm_name FROM "Dormitories" WHERE id = %s', (dorm_id,)).iloc[0]

        # 1. 查詢帳單
        bills_query = """
            SELECT id as bill_id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE id = ANY(%s)
            ORDER BY bill_type, bill_start_date;
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, (selected_bill_ids,))
        
        if bills_df.empty:
            return dorm_details, pd.DataFrame(), pd.DataFrame()

        min_bill_start = bills_df['bill_start_date'].min()
        max_bill_end = bills_df['bill_end_date'].max()
        
        # 2. 查詢員工的所有相關住宿歷史
        # 【核心修改】使用 CTE 先找出「期間內有在住」的人員 ID，再抓出這些人在該宿舍的「完整歷史」
        # 這樣才能正確判斷「連續住宿」的情況，避免因帳單截止日卡到換床日，導致看不到新紀錄而誤判為離住
        workers_query = """
            WITH TargetWorkers AS (
                SELECT DISTINCT ah.worker_unique_id
                FROM "AccommodationHistory" ah
                JOIN "Rooms" r ON ah.room_id = r.id
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                WHERE r.dorm_id = %s 
                  AND w.employer_name = %s
                  AND ah.start_date <= %s
                  AND (ah.end_date IS NULL OR ah.end_date >= %s)
            )
            SELECT
                w.unique_id, w.worker_name, w.native_name, ah.start_date, ah.end_date
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            JOIN TargetWorkers tw ON w.unique_id = tw.worker_unique_id
            WHERE r.dorm_id = %s
            ORDER BY w.worker_name, ah.start_date
        """
        # 注意參數順序：CTE(dorm, emp, end, start) -> Main(dorm)
        params = (dorm_id, employer_name, max_bill_end, min_bill_start, dorm_id)
        workers_df = _execute_query_to_dataframe(conn, workers_query, params)
        
        if workers_df.empty:
            return dorm_details, bills_df, pd.DataFrame()
            
        results = []
        
        # 3. 針對每位員工進行資料合併與計算
        for unique_id, group in workers_df.groupby('unique_id'):
            first_rec = group.iloc[0]
            worker_row = { 
                "姓名": first_rec['worker_name'], 
                "母語姓名": first_rec['native_name'] 
            }
            
            # 顯示用的起訖日
            # 入住日：取最早
            merged_start = pd.to_datetime(group['start_date']).min()
            worker_row["入住日期"] = merged_start.strftime('%Y-%m-%d')
            
            # 離住日：若「任何一筆」紀錄還在住 (end_date is null)，就代表他在住
            if group['end_date'].isnull().any():
                worker_row["離住日期"] = "" 
            else:
                # 否則取最後一天
                merged_end = pd.to_datetime(group['end_date']).max()
                worker_row["離住日期"] = merged_end.strftime('%Y-%m-%d')

            # 計算每張帳單的居住天數 (使用 Set 去重)
            for _, bill in bills_df.iterrows():
                bill_col_name = f"{bill['bill_type']}_{bill['bill_id']}"
                
                b_start = pd.to_datetime(bill['bill_start_date']).date()
                b_end = pd.to_datetime(bill['bill_end_date']).date()
                
                occupied_dates = set()
                
                for _, row in group.iterrows():
                    seg_start = pd.to_datetime(row['start_date']).date()
                    seg_end_val = row['end_date']
                    seg_end = pd.to_datetime(seg_end_val).date() if pd.notna(seg_end_val) else date(9999, 12, 31)
                    
                    # 計算交集
                    overlap_start = max(seg_start, b_start)
                    overlap_end = min(seg_end, b_end)
                    
                    if overlap_start <= overlap_end:
                        curr = overlap_start
                        while curr <= overlap_end:
                            occupied_dates.add(curr)
                            curr += timedelta(days=1)
                
                worker_row[f"{bill_col_name}_days"] = len(occupied_dates)
            
            results.append(worker_row)

        details_df = pd.DataFrame(results)

        # 4. 計算費用
        for _, bill in bills_df.iterrows():
            bill_col_name = f"{bill['bill_type']}_{bill['bill_id']}"
            
            if f"{bill_col_name}_days" in details_df.columns:
                total_days_for_bill = details_df[f"{bill_col_name}_days"].sum()
                
                if total_days_for_bill > 0:
                    cost_per_day = bill['amount'] / total_days_for_bill
                    details_df[f"{bill_col_name}_fee"] = details_df[f"{bill_col_name}_days"] * cost_per_day
                else:
                    details_df[f"{bill_col_name}_fee"] = 0
        
        return dorm_details, bills_df, details_df

    except Exception as e:
        print(f"產生客製化報表時發生錯誤: {e}")
        return None, None, None
    finally:
        if conn:
            conn.close()

def get_annual_financial_summary_report(year: int):
    """
    【v3.0 B04帳務版】產生年度宿舍財務總覽報表。
    1. 工人收入：改用 FeeHistory 加總。
    2. 費用結構：列出該年度的總收費人數與金額。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()

    params = {"year": str(year)}

    try:
        query = """
            WITH DateParams AS (
                SELECT
                    TO_DATE(%(year)s || '-01-01', 'YYYY-MM-DD') as start_date,
                    CURRENT_DATE as end_date
            ),
            -- 1. 計算實際收入 (FeeHistory)
            TotalIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(fh.amount) as total_worker_income
                FROM "FeeHistory" fh
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE 
                    fh.effective_date BETWEEN dp.start_date AND dp.end_date
                    AND ah.start_date <= fh.effective_date
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                GROUP BY r.dorm_id
                
                UNION ALL
                
                SELECT dorm_id, SUM(amount) as total_worker_income 
                FROM "OtherIncome" CROSS JOIN DateParams dp 
                WHERE transaction_date BETWEEN dp.start_date AND dp.end_date 
                GROUP BY dorm_id
            ),
            -- 2. 費用結構統計 (這部分維持用 FeeHistory 統計更有意義)
            ActiveResidents AS (
                SELECT DISTINCT ON (r.dorm_id, w.unique_id)
                    r.dorm_id, w.unique_id
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.end_date AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
            ),
            Headcount AS (
                SELECT dorm_id, COUNT(unique_id) as total_residents
                FROM ActiveResidents GROUP BY dorm_id
            ),
            -- 3. 總支出 (合約 + 帳單 + 攤銷)
            TotalExpense AS (
                SELECT l.dorm_id, SUM(COALESCE(l.monthly_rent, 0) * ((LEAST(COALESCE(l.lease_end_date, dp.end_date), dp.end_date)::date - GREATEST(l.lease_start_date, dp.start_date)::date + 1) / 30.4375)) as expense
                FROM "Leases" l JOIN "Dormitories" d ON l.dorm_id = d.id CROSS JOIN DateParams dp
                WHERE l.lease_start_date <= dp.end_date AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.start_date) AND l.payer = '我司' GROUP BY l.dorm_id
                UNION ALL
                SELECT dorm_id, SUM(COALESCE(amount, 0) * (LEAST(bill_end_date, dp.end_date)::date - GREATEST(bill_start_date, dp.start_date)::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0))
                FROM "UtilityBills" CROSS JOIN DateParams dp WHERE bill_start_date <= dp.end_date AND bill_end_date >= dp.start_date AND payer = '我司' GROUP BY dorm_id
                UNION ALL
                SELECT dorm_id, SUM((total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0)) * (LEAST(TO_DATE(amortization_end_month, 'YYYY-MM'), dp.end_date)::date - GREATEST(TO_DATE(amortization_start_month, 'YYYY-MM'), dp.start_date)::date + 1) / 30.4375) as expense
                FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.end_date AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.start_date GROUP BY dorm_id
            ),
            CurrentLease AS (
                SELECT DISTINCT ON (dorm_id) dorm_id, lease_end_date
                FROM "Leases"
                WHERE lease_start_date <= CURRENT_DATE AND (lease_end_date IS NULL OR lease_end_date >= CURRENT_DATE)
                ORDER BY dorm_id, lease_start_date DESC
            )
            SELECT
                d.original_address AS "宿舍地址",
                d.city AS "縣市",
                d.district AS "區域",
                d.person_in_charge AS "負責人",
                d.dorm_notes AS "宿舍備註", -- 新增
                COALESCE(h.total_residents, 0) AS "總人數",
                COALESCE(SUM(ti.total_worker_income), 0)::int AS "年度總收入", -- 加總所有收入來源
                COALESCE(SUM(te.expense), 0)::int AS "年度總支出 (我司)",
                (COALESCE(SUM(ti.total_worker_income), 0) - COALESCE(SUM(te.expense), 0))::int AS "淨損益 (我司)",
                MAX(cl.lease_end_date) AS "房租合約到期日"
            FROM "Dormitories" d
            LEFT JOIN Headcount h ON d.id = h.dorm_id
            LEFT JOIN TotalIncome ti ON d.id = ti.dorm_id
            LEFT JOIN TotalExpense te ON d.id = te.dorm_id
            LEFT JOIN CurrentLease cl ON d.id = cl.dorm_id
            WHERE d.primary_manager = '我司' AND h.total_residents > 0
            GROUP BY d.id, d.original_address, d.city, d.district, d.person_in_charge, d.dorm_notes, h.total_residents
            ORDER BY d.original_address;
        """
        return _execute_query_to_dataframe(conn, query, params)
    except Exception as e:
        print(f"產生年度財務總覽報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_employer_profit_loss_report(employer_names: list, year_month: str):
    """
    【v3.0 B04帳務版】產生雇主月度損益報表。
    收入：直接加總 FeeHistory。
    """
    if not employer_names: return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    params = {"employer_names": employer_names, "year_month": year_month}
    
    try:
        query = """
            WITH DateParams AS (
                SELECT 
                    TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') as first_day_of_month,
                    (TO_DATE(%(year_month)s || '-01', 'YYYY-MM-DD') + '1 month'::interval - '1 day'::interval)::date as last_day_of_month
            ),
            DormOccupancyDays AS (
                SELECT
                    r.dorm_id,
                    SUM(CASE WHEN w.employer_name = ANY(%(employer_names)s) THEN (LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1) ELSE 0 END) as employer_days,
                    SUM((LEAST(COALESCE(ah.end_date, dp.last_day_of_month), dp.last_day_of_month)::date - GREATEST(ah.start_date, dp.first_day_of_month)::date + 1)) as total_days
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE ah.start_date <= dp.last_day_of_month AND (ah.end_date IS NULL OR ah.end_date >= dp.first_day_of_month)
                GROUP BY r.dorm_id
            ),
            -- 收入計算：使用 FeeHistory
            EmployerIncome AS (
                SELECT
                    r.dorm_id,
                    SUM(fh.amount) as worker_income
                FROM "FeeHistory" fh
                JOIN "Workers" w ON fh.worker_unique_id = w.unique_id
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE w.employer_name = ANY(%(employer_names)s)
                  AND fh.effective_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                  AND ah.start_date <= fh.effective_date
                  AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
                GROUP BY r.dorm_id
            ),
            -- (支出計算 CTEs 維持不變)
            DormExpenses AS (
                SELECT
                    d.id as dorm_id,
                    COALESCE(l.monthly_rent, 0) AS landlord_rent,
                    COALESCE(u.utility_costs, 0) AS utility_costs,
                    COALESCE(a.management_costs, 0) AS management_costs
                FROM "Dormitories" d
                LEFT JOIN (
                    SELECT dorm_id, monthly_rent FROM (
                        SELECT l.dorm_id, l.monthly_rent, ROW_NUMBER() OVER(PARTITION BY l.dorm_id ORDER BY l.lease_start_date DESC) as rn
                        FROM "Leases" l
                        CROSS JOIN DateParams dp 
                        WHERE l.lease_start_date <= dp.last_day_of_month 
                          AND (l.lease_end_date IS NULL OR l.lease_end_date >= dp.first_day_of_month)
                          AND l.payer = '我司'
                    ) as sub_leases WHERE rn = 1
                ) l ON d.id = l.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(amount::decimal * (LEAST(bill_end_date, (SELECT last_day_of_month FROM DateParams))::date - GREATEST(bill_start_date, (SELECT first_day_of_month FROM DateParams))::date + 1) / NULLIF((bill_end_date - bill_start_date + 1), 0)) as utility_costs
                    FROM "UtilityBills" CROSS JOIN DateParams dp 
                    WHERE bill_start_date <= dp.last_day_of_month AND bill_end_date >= dp.first_day_of_month
                      AND payer = '我司'
                    GROUP BY dorm_id
                ) u ON d.id = u.dorm_id
                LEFT JOIN (
                    SELECT dorm_id, SUM(ROUND(total_amount::decimal / NULLIF(((EXTRACT(YEAR FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(YEAR FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) * 12 + (EXTRACT(MONTH FROM TO_DATE(amortization_end_month, 'YYYY-MM')) - EXTRACT(MONTH FROM TO_DATE(amortization_start_month, 'YYYY-MM'))) + 1), 0))) as management_costs
                    FROM "AnnualExpenses" CROSS JOIN DateParams dp WHERE TO_DATE(amortization_start_month, 'YYYY-MM') <= dp.last_day_of_month AND TO_DATE(amortization_end_month, 'YYYY-MM') >= dp.first_day_of_month GROUP BY dorm_id
                ) a ON d.id = a.dorm_id
            ),
            OtherDormIncome AS (
                 SELECT dorm_id, SUM(amount) as other_income
                 FROM "OtherIncome" CROSS JOIN DateParams dp
                 WHERE transaction_date BETWEEN dp.first_day_of_month AND dp.last_day_of_month
                 GROUP BY dorm_id
            )
            SELECT
                d.original_address AS "宿舍地址",
                d.dorm_notes AS "宿舍備註",
                COALESCE(ei.worker_income, 0)::int AS "移工每月扣款收入",
                ROUND(COALESCE(odi.other_income, 0) * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "其他收入",
                ROUND(de.landlord_rent * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "房東租金",
                ROUND(de.utility_costs * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "雜費(水電等)",
                ROUND(de.management_costs * (dod.employer_days / NULLIF(dod.total_days, 0)))::int AS "管理費用(保險等)"
            FROM DormOccupancyDays dod
            JOIN "Dormitories" d ON dod.dorm_id = d.id
            LEFT JOIN EmployerIncome ei ON dod.dorm_id = ei.dorm_id
            LEFT JOIN DormExpenses de ON dod.dorm_id = de.dorm_id
            LEFT JOIN OtherDormIncome odi ON dod.dorm_id = odi.dorm_id
            WHERE dod.employer_days > 0
            ORDER BY d.original_address;
        """
        
        df = _execute_query_to_dataframe(conn, query, params)
        
        if not df.empty:
            df["損益"] = (df["移工每月扣款收入"] + df["其他收入"]) - (df["房東租金"] + df["雜費(水電等)"] + df["管理費用(保險等)"])
            # 調整欄位順序
            df = df[["宿舍地址", "宿舍備註", "損益", "移工每月扣款收入", "其他收入", "房東租金", "雜費(水電等)", "管理費用(保險等)"]]
            
        return df

    except Exception as e:
        print(f"產生雇主損益報表時發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()

def get_excess_utility_report_data(
    dorm_ids: list, 
    employer_names: list, 
    bill_ids: list, 
    fixed_subsidy: int, 
    include_external_workers: bool,
    calculation_mode: str = 'bill', 
    report_start_date=None, 
    report_end_date=None
):
    """
    【v2.5 合併修正版】產生超額水電費分攤報表。
    修正：針對「同日換宿/換床」的員工，將多筆歷史紀錄合併為單一人員計算。
    1. 避免 12/15 在舊房與新房重複計算天數。
    2. 正確判斷「最終離住日」（若新房還在住，報表就不會顯示離住）。
    """
    if not dorm_ids or not employer_names or not bill_ids:
        return None, None, None, None, None

    conn = database.get_db_connection()
    if not conn: return None, None, None, None, None

    try:
        from datetime import date, timedelta # 引入時間計算模組

        # 型別轉換 (確保是 list)
        safe_dorm_ids = list(int(i) for i in (dorm_ids if isinstance(dorm_ids, list) else [dorm_ids]))
        safe_bill_ids = list(int(i) for i in (bill_ids if isinstance(bill_ids, list) else [bill_ids]))
        safe_employer_names = list(employer_names if isinstance(employer_names, list) else [employer_names])

        # 1. 獲取宿舍基本信息
        dorm_query = 'SELECT original_address FROM "Dormitories" WHERE id = ANY(%s)'
        dorm_details_df = _execute_query_to_dataframe(conn, dorm_query, (safe_dorm_ids,))
        dorm_address_list = dorm_details_df['original_address'].tolist()
        
        # 2. 獲取帳單
        bills_query = """
            SELECT id as bill_id, bill_type, bill_start_date, bill_end_date, amount
            FROM "UtilityBills"
            WHERE id = ANY(%s) AND (bill_type = '水費' OR bill_type = '電費')
            ORDER BY bill_type, bill_start_date;
        """
        bills_df = _execute_query_to_dataframe(conn, bills_query, (safe_bill_ids,))
        
        if bills_df.empty:
            return dorm_address_list, pd.DataFrame(), pd.DataFrame(), None, None

        # --- 計算區間與總金額邏輯 ---
        calc_start = None
        calc_end = None
        total_utility_cost = 0
        
        if calculation_mode == 'date_range':
            # 模式 A：依日期區間 (需按比例分攤帳單金額)
            calc_start = report_start_date if report_start_date else bills_df['bill_start_date'].min()
            calc_end = report_end_date if report_end_date else bills_df['bill_end_date'].max()
            
            for _, bill in bills_df.iterrows():
                b_start = pd.to_datetime(bill['bill_start_date']).date()
                b_end = pd.to_datetime(bill['bill_end_date']).date()
                b_amount = bill['amount']
                
                total_bill_days = (b_end - b_start).days + 1
                overlap_start = max(b_start, calc_start)
                overlap_end = min(b_end, calc_end)
                
                if overlap_start <= overlap_end:
                    overlap_days = (overlap_end - overlap_start).days + 1
                    ratio = overlap_days / total_bill_days if total_bill_days > 0 else 0
                    total_utility_cost += b_amount * ratio
        else:
            # 模式 B：依帳單 (全額)
            calc_start = bills_df['bill_start_date'].min()
            calc_end = bills_df['bill_end_date'].max()
            total_utility_cost = bills_df['amount'].sum()

        # 3. 獲取「計算區間內」的所有相關住宿紀錄
        external_filter_sql = ""
        if not include_external_workers:
            external_filter_sql = " AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')" 
            
        # 這裡只撈取原始資料，不計算 lived_days，改由 Python 統一合併計算
        worker_raw_query = f"""
            SELECT
                w.unique_id, w.worker_name, w.employer_name, w.native_name, 
                w.passport_number, w.nationality, w.gender,
                ah.start_date, ah.end_date
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE r.dorm_id = ANY(%s)
              AND ah.start_date <= %s::date
              AND (ah.end_date IS NULL OR ah.end_date >= %s::date)
              {external_filter_sql}
        """
        raw_records_df = _execute_query_to_dataframe(conn, worker_raw_query, (safe_dorm_ids, calc_end, calc_start))
        
        if raw_records_df.empty:
            return dorm_address_list, bills_df, pd.DataFrame(), 0.0, 0.0

        # 4. 【核心修改】合併同一位員工的紀錄並計算不重複天數
        merged_results = []
        
        # 依 unique_id 分組
        for unique_id, group in raw_records_df.groupby('unique_id'):
            first_row = group.iloc[0] # 取基本資料
            
            # 使用 Set (集合) 計算該員工在 calc_start ~ calc_end 期間的實際居住天數
            # 這能完美解決 "換房當天被重複計算" 的問題
            occupied_dates = set()
            
            for _, row in group.iterrows():
                # 該段歷史的區間
                seg_start = pd.to_datetime(row['start_date']).date()
                seg_end_val = row['end_date']
                seg_end = pd.to_datetime(seg_end_val).date() if pd.notna(seg_end_val) else date(9999, 12, 31)
                
                # 計算與「報表計算區間」的交集
                overlap_start = max(seg_start, calc_start)
                overlap_end = min(seg_end, calc_end)
                
                if overlap_start <= overlap_end:
                    curr = overlap_start
                    while curr <= overlap_end:
                        occupied_dates.add(curr)
                        curr += timedelta(days=1)
            
            lived_days = len(occupied_dates)
            if lived_days == 0: continue # 理論上不會發生，以防萬一

            # 決定顯示用的起訖日
            # 入住日：這段期間最早的紀錄
            display_start = group['start_date'].min()
            
            # 離住日：若任一筆紀錄是「在住」(end_date is Null)，則視為在住；否則取最晚日期
            is_still_living = group['end_date'].isnull().any()
            if is_still_living:
                display_end = None
            else:
                display_end = group['end_date'].max()

            merged_results.append({
                'unique_id': unique_id,
                'worker_name': first_row['worker_name'],
                'employer_name': first_row['employer_name'],
                'native_name': first_row['native_name'],
                'passport_number': first_row['passport_number'],
                'nationality': first_row['nationality'],
                'gender': first_row['gender'],
                'start_date': display_start,
                'end_date': display_end,
                'lived_days': lived_days
            })

        worker_days_df = pd.DataFrame(merged_results)

        # 5. 計算費用 (分攤)
        total_dorm_days = worker_days_df['lived_days'].sum()
        avg_days_per_month = 30.4375 
        
        expected_total_subsidy = total_dorm_days * (fixed_subsidy / avg_days_per_month)
        total_excess_cost = total_utility_cost - expected_total_subsidy
        
        charge_per_day = 0.0
        if total_dorm_days > 0 and total_excess_cost > 0:
            charge_per_day = total_excess_cost / total_dorm_days

        # 6. 應用到每位員工
        worker_days_df['daily_charge'] = charge_per_day
        worker_days_df['final_bill_amount'] = (worker_days_df['lived_days'] * worker_days_df['daily_charge']).round().astype(int)
        
        # 7. 彙總目標雇主 (篩選)
        target_employer_df = worker_days_df[worker_days_df['employer_name'].isin(safe_employer_names)].copy()
        
        if target_employer_df.empty:
            return dorm_address_list, bills_df, pd.DataFrame(), 0.0, total_excess_cost

        # 8. 整理輸出欄位
        report_df = target_employer_df[[
            'employer_name', 'worker_name', 'native_name', 
            'passport_number', 'nationality', 'gender',
            'start_date', 'end_date', 'lived_days', 'final_bill_amount'
        ]].rename(columns={
            'employer_name': '雇主', 'worker_name': '姓名', 'native_name': '英文姓名',
            'passport_number': '護照號碼', 'nationality': '國籍', 'gender': '性別',
            'start_date': '入住日期', 'end_date': '離住日期', 'lived_days': '居住天數',
            'final_bill_amount': '應收水電費'
        })
        
        total_charge = report_df['應收水電費'].sum()
        
        return dorm_address_list, bills_df, report_df, total_charge, total_excess_cost
    
    except Exception as e:
        print(f"Error in get_excess_utility_report_data: {e}")
        return None, None, None, None, None
    finally:
        if conn: conn.close()

def get_employers_in_dorms_for_period(dorm_ids, start_date, end_date) -> list:
    """
    獲取在指定宿舍列表和日期範圍內有住宿紀錄的雇主名稱。
    """
    if not dorm_ids or not start_date or not end_date:
        return []
    conn = database.get_db_connection()
    if not conn: return []
    
    try:
        # 【修正】型別檢查與列表轉換
        if isinstance(dorm_ids, int):
            target_ids = [dorm_ids]
        else:
            target_ids = dorm_ids
            
        safe_dorm_ids = list(int(i) for i in target_ids)
        
        query = """
            SELECT DISTINCT
                w.employer_name
            FROM "AccommodationHistory" ah
            JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
            JOIN "Rooms" r ON ah.room_id = r.id
            WHERE 
                r.dorm_id = ANY(%s)
                AND ah.start_date <= %s
                AND (ah.end_date IS NULL OR ah.end_date >= %s)
                AND (w.special_status IS NULL OR w.special_status NOT ILIKE '%%掛宿外住%%')
            ORDER BY w.employer_name;
        """
        df = _execute_query_to_dataframe(conn, query, (safe_dorm_ids, end_date, start_date))
        return df['employer_name'].tolist()
        
    except Exception as e:
        print(f"Error getting employers in dorms for period: {e}")
        return []
    finally:
        if conn: conn.close()