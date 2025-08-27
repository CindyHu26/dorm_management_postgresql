import sqlite3
import pandas as pd
import database # 引用我們修改後的 database.py
from sqlalchemy import create_engine, text
import sys
import os

def get_sqlite_connection(db_name="dorm_management.db"):
    """一個獨立的函式，專門用來連線到舊的 SQLite 資料庫。"""
    try:
        db_path = os.path.join(database.get_base_path(), db_name)
        if not os.path.exists(db_path):
            print(f"錯誤：找不到來源資料庫檔案 '{db_path}'。請確認檔案是否存在於專案根目錄。")
            sys.exit(1)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        print(f"INFO: 已成功連線至來源 SQLite 資料庫: {db_path}")
        return conn
    except Exception as e:
        print(f"錯誤：連線到 SQLite 資料庫失敗: {e}")
        sys.exit(1)

def clean_and_migrate_table(table_name, sqlite_conn, connection):
    """
    將單一表格從 SQLite 遷移到 PostgreSQL，並在過程中進行資料清洗。
    此函式在一個已存在的交易 (connection) 中執行。
    """
    print(f"開始處理表格: {table_name}...")
    
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', sqlite_conn)
        if df.empty:
            print(f"  - 表格 {table_name} 是空的，跳過。")
            return

        df = df.where(pd.notna(df), None)

        # --- 根據不同的表格，進行特定的資料清洗 ---
        if table_name == 'Workers':
            if 'special_status' in df.columns:
                df = df.drop(columns=['special_status'])
                print("  - INFO: 已移除舊的 'special_status' 欄位。")
            if 'utilities_fee' not in df.columns:
                df['utilities_fee'] = 0
            if 'cleaning_fee' not in df.columns:
                df['cleaning_fee'] = 0

        if table_name == 'UtilityBills':
            if 'is_invoiced' in df.columns:
                df['is_invoiced'] = df['is_invoiced'].apply(lambda x: bool(x) if pd.notna(x) and int(x) == 1 else False).astype(bool)
                print("  - INFO: 已將 'is_invoiced' 欄位轉換為布林值。")
        
        if table_name == 'WorkerStatusHistory':
            original_count = len(df)
            df.dropna(subset=['worker_unique_id'], inplace=True)
            df = df[df['worker_unique_id'] != ''] # 同時過濾空字串
            removed_count = original_count - len(df)
            if removed_count > 0:
                print(f"  - WARNING: 移除了 {removed_count} 筆沒有 'worker_unique_id' 的無效歷史紀錄。")

        # --- 使用 to_sql 寫入資料 ---
        df.to_sql(table_name, connection, if_exists='append', index=False, chunksize=1000, method='multi')
        print(f"  - 成功準備 {len(df)} 筆資料到 {table_name}。")

    except Exception as e:
        # 如果發生錯誤，拋出異常，讓外層的交易區塊可以捕捉到並復原
        print(f"  - 嚴重錯誤：處理表格 {table_name} 失敗: {e}")
        raise

if __name__ == "__main__":
    print("===== 開始執行資料庫遷移程序 =====")
    
    TABLE_ORDER = [
        'Dormitories', 'Rooms', 'Workers', 'Meters', 'Leases',
        'DormitoryEquipment', 'UtilityBills', 'AnnualExpenses', 'OtherIncome',
        'WorkerStatusHistory'
    ]

    sqlite_conn = None
    engine = None
    try:
        sqlite_conn = get_sqlite_connection()
        config = database.get_db_config()
        
        db_type = config.get('type').lower()
        if db_type == 'postgresql':
            conn_str = f"postgresql+psycopg2://{config.get('user')}:{config.get('password')}@{config.get('host')}:{config.get('port')}/{config.get('dbname')}"
        else:
            raise ValueError("此遷移腳本目前設定為遷移至 PostgreSQL，請檢查 config.ini。")
            
        engine = create_engine(conn_str)

        # 使用一個主交易來包覆所有操作
        with engine.connect() as connection:
            print("\nINFO: 正在啟動一個主交易...")
            with connection.begin(): # <--- 關鍵！這會開始一個交易
                print("INFO: 交易已啟動。開始清空目標表格...")
                
                # 反向順序清空表格，避免違反外鍵約束
                for table_name in reversed(TABLE_ORDER):
                    print(f"  - 正在清空 {table_name}...")
                    # 使用 text() 來確保 SQL 字串被正確處理
                    connection.execute(text(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE;'))
                
                print("INFO: 目標表格已清空。開始逐一遷移資料...")

                # 逐一遷移表格
                for table in TABLE_ORDER:
                    clean_and_migrate_table(table, sqlite_conn, connection)
                
                print("\nINFO: 所有資料已成功準備，交易即將提交...")
            
            # 當離開 with connection.begin() 區塊時，如果沒有錯誤，交易會自動提交
            print("INFO: 交易已成功提交！")

        print("\n===== 所有資料遷移完成！ =====")
        print("請到您的 PostgreSQL 資料庫中檢查資料是否正確。")

    except Exception as e:
        print(f"\n遷移過程中發生未預期的錯誤，所有操作已被復原: {e}")
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if engine:
            engine.dispose()