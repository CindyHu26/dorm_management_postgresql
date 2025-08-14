import pandas as pd
import sqlite3
from datetime import datetime
from typing import Callable
import traceback

# 引用我們之前建立的模組
import database

def run_update_process(
    fresh_df: pd.DataFrame,
    log_callback: Callable[[str], None]
):
    """
    執行核心的資料庫更新流程。

    Args:
        fresh_df (pd.DataFrame): 從 data_processor 來的最新、乾淨的移工資料。
        log_callback (Callable[[str], None]): 日誌回呼函式。
    """
    log_callback("\n===== 開始執行核心資料庫更新程序 =====")
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    try:
        conn = database.get_db_connection()
        if not conn:
            log_callback("CRITICAL: 無法連接到資料庫，更新程序終止。")
            return

        # 1. 讀取資料庫中現有的所有移工資料
        try:
            # 讀取所有欄位，以便保留手動維護的資料
            db_df = pd.read_sql('SELECT * FROM Workers', conn)
            log_callback(f"INFO: 資料庫中現有 {len(db_df)} 筆移工總資料。")
        except (pd.io.sql.DatabaseError, ValueError): 
            db_df = pd.DataFrame(columns=['unique_id']) # 如果表格為空或不存在，建立一個空表
            log_callback("INFO: 資料庫中尚無移工資料，本次抓取將全部視為新增。")

        # 2. 準備ID集合以供比對
        fresh_ids = set(fresh_df['unique_id'])
        db_ids = set(db_df['unique_id'])

        # 3. 找出三種狀態的人員ID
        added_ids = fresh_ids - db_ids
        deleted_ids = db_ids - fresh_ids
        existing_ids = fresh_ids.intersection(db_ids)

        log_callback(f"比對完成 -> 新增: {len(added_ids)} 人, 離職/資料移除: {len(deleted_ids)} 人, 狀態不變: {len(existing_ids)} 人")

        # 4. 處理離職員工 (軟刪除)
        # 我們只處理由系統管理的員工，手動管理的會被過濾掉
        if not db_df.empty:
            for uid in deleted_ids:
                # 找到該員工在資料庫中的紀錄
                worker_record = db_df[db_df['unique_id'] == uid]
                if not worker_record.empty:
                    # 【關鍵保護機制】檢查資料來源
                    if worker_record.iloc[0]['data_source'] == '系統自動更新':
                        # 如果住宿迄日是空的，才更新它
                        if pd.isna(worker_record.iloc[0]['accommodation_end_date']):
                            db_df.loc[db_df['unique_id'] == uid, 'accommodation_end_date'] = today_str
                            log_callback(f"INFO: 系統管理的移工 '{uid}' 已不在最新名單，更新住宿迄日。")
                    else:
                        log_callback(f"INFO: 移工 '{uid}' 為手動管理，略過狀態更新。")
        
        # 5. 準備最終要寫入資料庫的完整DataFrame
        #    核心思想：以最新的資料(fresh_df)為基礎，合併舊資料庫中需要保留的欄位
        
        # 定義需要從舊資料庫保留的欄位 (所有手動維護的欄位)
        manual_cols = [
            'unique_id', 'room_id', 'accommodation_start_date', 'accommodation_end_date',
            'monthly_fee', 'fee_notes', 'payment_method', 'data_source',
            'worker_notes', 'special_status'
        ]
        # 篩選出db_df中實際存在的欄位
        existing_manual_cols = [col for col in manual_cols if col in db_df.columns]

        if not db_df.empty:
            final_df = pd.merge(fresh_df, db_df[existing_manual_cols], on='unique_id', how='left')
        else:
            final_df = fresh_df.copy()

        # 6. 為新進、在職員工設定狀態與預設值
        for index, row in final_df.iterrows():
            uid = row['unique_id']
            # 對於新員工
            if uid in added_ids:
                # accommodation_start_date 預設為入境日
                final_df.loc[index, 'accommodation_start_date'] = row['arrival_date']
                # data_source 預設為系統更新
                final_df.loc[index, 'data_source'] = '系統自動更新'
            
            # 對於所有在職的員工 (新進+既有)，確保其住宿迄日為空
            if uid in fresh_ids:
                 final_df.loc[index, 'accommodation_end_date'] = None

        # 7. 將已標記為"離職"的舊員工，以及"手動管理"的員工加回最終表格
        if not db_df.empty:
            # 篩選出所有不在最新名單中的人(包含軟刪除和手動管理的)
            archived_df = db_df[~db_df['unique_id'].isin(fresh_ids)]
            # 合併回主表
            final_df = pd.concat([final_df, archived_df], ignore_index=True)

        # 8. 執行資料庫寫入
        log_callback("INFO: 正在將最終整合結果寫入資料庫...")
        # 使用 'replace' 會先刪除舊表再建立新表並寫入，是原子性操作，非常安全
        final_df.to_sql('Workers', conn, if_exists='replace', index=False)
        log_callback(f"SUCCESS: 資料庫更新完成！目前資料庫總筆數: {len(final_df)}")

    except Exception as e:
        log_callback(f"CRITICAL: 更新資料庫時發生嚴重錯誤: {e}\n{traceback.format_exc()}")
        if 'conn' in locals() and conn:
            conn.rollback()
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == '__main__':
    print("--- updater.py 模組 ---")
    print("這個模組包含了核心的資料庫比對與更新邏輯。")
    print("它不應被獨立執行，而是由主應用程式(main_app.py)調用。")