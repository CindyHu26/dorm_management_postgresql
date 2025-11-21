import streamlit as st
import pandas as pd
from data_models import finance_model, dormitory_model, employer_dashboard_model

def render():
    """渲染「費用標準與異常儀表板」 (動態欄位版)"""
    st.header("費用標準與異常儀表板")
    st.info("此儀表板會自動掃描資料庫中**所有出現過的費用類型**，並分析各群體的收費標準。")

    # --- 1. 篩選條件 (維持不變) ---
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

    # --- 2. 獲取資料 (使用新函式) ---
    filters = {
        "dorm_ids": selected_dorms if selected_dorms else None,
        "employer_names": selected_employers if selected_employers else None
    }

    with st.spinner("正在分析費用結構..."):
        # 取得長表格式資料 [宿舍, 雇主, 姓名, ..., 費用類型, 金額]
        raw_long_df = finance_model.get_dynamic_fee_data_for_dashboard(filters)

    if raw_long_df.empty:
        st.warning("查無符合條件的人員費用資料。")
        return

    # --- 3. 資料處理：長表轉寬表 (Pivot) ---
    # 處理特殊狀況空值
    raw_long_df['特殊狀況'] = raw_long_df['特殊狀況'].fillna('一般').replace('', '一般')

    # 使用 pivot_table 將「費用類型」轉為欄位
    # index 是唯一識別一個人的欄位
    pivot_df = raw_long_df.pivot_table(
        index=['宿舍地址', '雇主', '特殊狀況', '姓名', '房號'], 
        columns='費用類型', 
        values='金額', 
        fill_value=0 # 沒該費用的填 0
    ).reset_index()

    # 自動取得所有費用欄位名稱
    fee_cols = [c for c in pivot_df.columns if c not in ['宿舍地址', '雇主', '特殊狀況', '姓名', '房號']]
    
    # --- 4. 異常分析邏輯 (動態迴圈) ---
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
            # 計算眾數 (Mode) 作為 "標準費用"
            modes = group[col].mode()
            # 如果有多個眾數，取最大值 (或是取第一個)，這裡假設標準只有一個
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

    # --- 5. 顯示彙總表 (動態欄位) ---
    st.subheader("📊 收費標準總覽")
    st.info(f"系統目前偵測到 {len(fee_cols)} 種費用類型：{', '.join(fee_cols)}")

    if not summary_df.empty:
        # 設定顯示欄位順序
        cols_order = ["宿舍", "雇主", "特殊狀況", "總人數"]
        for col in fee_cols:
            cols_order.append(f"標準{col}")
            cols_order.append(f"{col}異常")
        
        # 動態產生 Column Config
        column_config = {
            "總人數": st.column_config.NumberColumn(format="%d 人"),
            "特殊狀況": st.column_config.TextColumn(help="以此狀態區分收費標準"),
        }
        for col in fee_cols:
            column_config[f"標準{col}"] = st.column_config.NumberColumn(label=f"{col}", format="$%d")
            column_config[f"{col}異常"] = st.column_config.NumberColumn(label="異常", help=f"{col}的異常人數")

        st.dataframe(
            summary_df[cols_order],
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
        
        # 篩選器也動態化
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