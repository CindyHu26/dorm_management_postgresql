# views/fee_dashboard_view.py (v3.1 - 支援自訂欄位排序)

import streamlit as st
import pandas as pd
import json
import os
from data_models import finance_model, dormitory_model, employer_dashboard_model

# --- 新增：讀取費用設定檔 ---
FEE_CONFIG_FILE = "fee_config.json"

def load_fee_order():
    """讀取設定檔中的費用類型順序"""
    default_order = ["房租", "水電費", "清潔費", "宿舍復歸費", "充電清潔費"]
    
    if os.path.exists(FEE_CONFIG_FILE):
        try:
            with open(FEE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 回傳設定檔中的 internal_types，若無則回傳預設
                return config.get("internal_types", default_order)
        except Exception:
            pass
    return default_order

def render():
    """渲染「費用標準與異常儀表板」"""
    st.header("費用標準與異常儀表板")
    st.info("此儀表板會自動掃描資料庫中**所有出現過的費用類型**，並依照您在「財務爬取與設定」頁面定義的順序排列。")

    # --- 1. 篩選條件 ---
    @st.cache_data
    def get_options():
        dorms = dormitory_model.get_my_company_dorms_for_selection()
        employers = employer_dashboard_model.get_all_employers()
        return dorms, employers

    dorms_list, employers_list = get_options()
    dorm_map = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms_list}

    col1, col2 = st.columns(2)
    selected_dorms = col1.multiselect("篩選宿舍 (預設全部)", options=list(dorm_map.keys()), format_func=lambda x: dorm_map[x])
    selected_employers = col2.multiselect("篩選雇主 (預設全部)", options=employers_list)

    if st.button("🔄 重新整理數據"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    # --- 2. 獲取資料 ---
    filters = {
        "dorm_ids": selected_dorms if selected_dorms else None,
        "employer_names": selected_employers if selected_employers else None
    }

    with st.spinner("正在分析費用結構..."):
        # 取得長表格式資料
        raw_long_df = finance_model.get_dynamic_fee_data_for_dashboard(filters)

    if raw_long_df.empty:
        st.warning("查無符合條件的人員費用資料。")
        return

    # --- 3. 資料處理：長表轉寬表 (Pivot) ---
    raw_long_df['特殊狀況'] = raw_long_df['特殊狀況'].fillna('一般').replace('', '一般')

    # 使用 pivot_table 將「費用類型」轉為欄位
    pivot_df = raw_long_df.pivot_table(
        index=['宿舍地址', '雇主', '特殊狀況', '姓名', '房號'], 
        columns='費用類型', 
        values='金額', 
        fill_value=0
    ).reset_index()

    # --- 【核心修改】排序欄位 ---
    # 1. 找出資料中實際出現的所有費用欄位
    data_fee_cols = [c for c in pivot_df.columns if c not in ['宿舍地址', '雇主', '特殊狀況', '姓名', '房號']]
    
    # 2. 讀取使用者設定的偏好順序
    preferred_order = load_fee_order()
    
    # 3. 進行排序：
    #    邏輯：如果在偏好清單中，依照清單順序 (index)；
    #         如果不在清單中 (新出現的)，則排在最後面 (999)。
    fee_cols = sorted(data_fee_cols, key=lambda x: preferred_order.index(x) if x in preferred_order else 999)

    # --- 4. 異常分析邏輯 ---
    summary_data = []
    exception_details = []

    grouped = pivot_df.groupby(['宿舍地址', '雇主', '特殊狀況'])

    for (dorm, emp, status), group in grouped:
        group_stats = {
            "宿舍": dorm,
            "雇主": emp,
            "特殊狀況": status,
            "總人數": len(group)
        }
        
        for col in fee_cols:
            # 計算標準費用 (眾數)
            modes = group[col].mode()
            standard_fee = modes[0] if not modes.empty else 0
            
            group_stats[f"標準{col}"] = standard_fee
            
            # 找出異常
            exceptions = group[group[col] != standard_fee]
            
            if not exceptions.empty:
                group_stats[f"{col}異常"] = len(exceptions)
                
                for _, row in exceptions.iterrows():
                    exception_details.append({
                        "宿舍": dorm,
                        "雇主": emp,
                        "特殊狀況": status,
                        "姓名": row['姓名'],
                        "房號": row['房號'],
                        "費用項目": col,
                        "標準金額": standard_fee,
                        "實際金額": row[col]
                    })
            else:
                group_stats[f"{col}異常"] = 0

        summary_data.append(group_stats)

    summary_df = pd.DataFrame(summary_data)
    exceptions_df = pd.DataFrame(exception_details)

    # --- 5. 顯示彙總表 ---
    st.subheader("📊 收費標準總覽")
    
    if not summary_df.empty:
        # 設定顯示欄位順序 (這裡也要依照排序後的 fee_cols)
        cols_order = ["宿舍", "雇主", "特殊狀況", "總人數"]
        for col in fee_cols:
            cols_order.append(f"標準{col}")
            cols_order.append(f"{col}異常")
        
        column_config = {
            "總人數": st.column_config.NumberColumn(format="%d 人"),
            "特殊狀況": st.column_config.TextColumn(help="以此狀態區分收費標準"),
        }
        for col in fee_cols:
            column_config[f"標準{col}"] = st.column_config.NumberColumn(label=f"{col}", format="$%d")
            column_config[f"{col}異常"] = st.column_config.NumberColumn(label="異常", help=f"{col}的異常人數")

        st.dataframe(
            summary_df[cols_order], # 使用排序後的順序
            width="stretch",
            hide_index=True,
            column_config=column_config
        )

    # --- 6. 顯示特例細節 ---
    st.markdown("---")
    st.subheader("🔍 特例人員清單")
    
    if exceptions_df.empty:
        st.success("恭喜！所有人員的收費皆符合標準。")
    else:
        st.warning(f"共發現 {len(exceptions_df)} 筆收費特例。")
        
        # 篩選器也依照排序後的順序顯示
        filter_ex_col = st.multiselect("篩選費用項目", options=fee_cols, default=fee_cols)
        
        if filter_ex_col:
            filtered_ex_df = exceptions_df[exceptions_df['費用項目'].isin(filter_ex_col)]
            
            st.dataframe(
                filtered_ex_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "標準金額": st.column_config.NumberColumn(format="$%d"),
                    "實際金額": st.column_config.NumberColumn(format="$%d"),
                }
            )