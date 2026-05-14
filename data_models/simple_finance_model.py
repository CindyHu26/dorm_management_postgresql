# data_models/simple_finance_model.py
import pandas as pd
from datetime import datetime
import database

def get_simplified_annual_finance_data(year: int):
    """
    計算指定年度的簡易財務收支。
    長官試算邏輯：
    - 如果房租是我們出，每月試算費用 = 房租 * 1.2
    - 如果房租不是我們出，但變動費用攤銷是我們出，每月試算費用 = 房租 * 0.2
    - 如果都不是我們出，每月試算費用 = 0
    """
    conn = database.get_db_connection()
    if not conn: 
        return pd.DataFrame()
    
    today = datetime.now().date()
    current_year = today.year
    
    start_date_str = f"{year}-01-01"
    if year < current_year:
        end_date_str = f"{year}-12-31"
    else:
        end_date_str = today.strftime('%Y-%m-%d')
        
    try:
        # 取得總收入與宿舍屬性的 SQL 查詢 (沿用系統原本的穩定邏輯)
        query = """
            WITH DateParams AS (
                SELECT
                    %(start_date)s::date as start_date,
                    %(end_date)s::date as end_date
            ),
            ResidentEmployers AS (
                SELECT 
                    r.dorm_id, 
                    STRING_AGG(DISTINCT w.employer_name, ', ') as employers
                FROM "AccommodationHistory" ah
                JOIN "Workers" w ON ah.worker_unique_id = w.unique_id
                JOIN "Rooms" r ON ah.room_id = r.id
                CROSS JOIN DateParams dp
                WHERE 
                    ah.start_date <= dp.end_date
                    AND (ah.end_date IS NULL OR ah.end_date >= dp.start_date)
                GROUP BY r.dorm_id
            ),
            WorkerIncome AS (
                SELECT 
                    r.dorm_id, 
                    SUM(fh.amount) as income 
                FROM "FeeHistory" fh 
                JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id 
                JOIN "Rooms" r ON ah.room_id = r.id 
                JOIN "Dormitories" d ON r.dorm_id = d.id 
                CROSS JOIN DateParams dp
                WHERE 
                    fh.effective_date BETWEEN dp.start_date AND dp.end_date 
                    AND ah.start_date <= fh.effective_date 
                    AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date) 
                    AND d.primary_manager = '我司' 
                GROUP BY r.dorm_id
            ),
            OtherIncome AS (
                SELECT dorm_id, SUM(amount) as income 
                FROM "OtherIncome" CROSS JOIN DateParams dp 
                WHERE transaction_date BETWEEN dp.start_date AND dp.end_date 
                GROUP BY dorm_id
            ),
            PassThroughIncome AS (
                SELECT b.dorm_id, SUM(b.amount::decimal * (LEAST(b.bill_end_date, dp.end_date)::date - GREATEST(b.bill_start_date, dp.start_date)::date + 1) / NULLIF((b.bill_end_date - b.bill_start_date + 1), 0)) as total_pass_through_income 
                FROM "UtilityBills" b CROSS JOIN DateParams dp 
                WHERE b.is_pass_through = TRUE AND b.bill_start_date <= dp.end_date AND b.bill_end_date >= dp.start_date 
                GROUP BY b.dorm_id
            ),
            ActiveLease AS (
                -- 取得每個宿舍當前或最近的合約租金與支付方
                SELECT DISTINCT ON (dorm_id)
                    dorm_id,
                    monthly_rent,
                    payer as lease_payer
                FROM "Leases"
                ORDER BY dorm_id, lease_start_date DESC
            )
            SELECT
                d.id,
                d.original_address AS "宿舍地址",
                re.employers AS "雇主",
                (COALESCE(wi.income, 0) + COALESCE(oi.income, 0) + COALESCE(pti.total_pass_through_income, 0))::int AS "實際總收入",
                COALESCE(al.monthly_rent, 0)::int AS "月租金基準",
                d.rent_payer AS "宿舍_租金支付方",
                d.utilities_payer AS "宿舍_水電支付方",
                al.lease_payer AS "合約_租金支付方",
                d.dorm_notes AS "宿舍備註"
            FROM "Dormitories" d
            LEFT JOIN ResidentEmployers re ON d.id = re.dorm_id
            LEFT JOIN WorkerIncome wi ON d.id = wi.dorm_id
            LEFT JOIN OtherIncome oi ON d.id = oi.dorm_id
            LEFT JOIN PassThroughIncome pti ON d.id = pti.dorm_id
            LEFT JOIN ActiveLease al ON d.id = al.dorm_id
            WHERE d.primary_manager = '我司'
        """
        df = pd.read_sql(query, conn, params={"start_date": start_date_str, "end_date": end_date_str})
        
        if df.empty:
            return df
            
        # 實作長官的試算邏輯
        def calc_monthly_expense(row):
            rent = row["月租金基準"]
            rent_payer_dorm = row["宿舍_租金支付方"]
            rent_payer_lease = row["合約_租金支付方"]
            util_payer = row["宿舍_水電支付方"]
            
            # 判斷是否由我司支付房租 (合約有紀錄 或 宿舍登記為我司)
            if rent_payer_lease == '我司' or rent_payer_dorm == '我司':
                return rent * 1.2
            # 判斷房租非我司出，但水電攤銷等由我司支付
            elif util_payer == '我司':
                return rent * 0.2
            else:
                # 房租、其他費用都不是我們出
                return 0

        # 計算試算結果並轉為整數
        df["試算月費用"] = df.apply(calc_monthly_expense, axis=1).astype(int)
        df["試算年支出"] = df["試算月費用"] * 12  # 年化處理：月費用 * 12
        df["試算淨損益"] = df["實際總收入"] - df["試算年支出"]
        
        # 篩選要呈現給前端視圖的欄位
        result_df = df[[
            "宿舍地址", "雇主", "實際總收入", "月租金基準", 
            "試算月費用", "試算年支出", "試算淨損益", "宿舍備註"
        ]].copy()
        
        return result_df
        
    except Exception as e:
        print(f"簡易財務報表發生錯誤: {e}")
        return pd.DataFrame()
    finally:
        conn.close()