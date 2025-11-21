# views/fee_dashboard_view.py (v1.1 - 加入特殊狀況分組)

import streamlit as st
import pandas as pd
from data_models import finance_model, dormitory_model, employer_dashboard_model

def render():
    """渲染「費用標準與異常儀表板」"""
    st.header("費用標準與異常儀表板")
    st.info("此儀表板自動分析各「宿舍」、「雇主」與「特殊狀況」的收費慣例（標準），並列出收費不同的特例人員。")

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
        raw_df = finance_model.get_workers_for_fee_management(filters)

    if raw_df.empty:
        st.warning("查無符合條件的人員資料。")
        return

    # --- 3. 數據處理核心邏輯 ---
    # 定義要分析的費用欄位
    fee_cols = ["月費(房租)", "水電費", "清潔費", "宿舍復歸費", "充電清潔費"]
    
    analysis_df = raw_df.copy()
    
    # 【核心修改 1】處理特殊狀況：填補空值為 '一般'
    # 這樣 '一般' 員工就會被歸為同一組，而有特殊狀況的會分開
    analysis_df['特殊狀況'] = analysis_df['特殊狀況'].fillna('一般').replace('', '一般')

    # 預處理：填補費用空值為 0 以利計算
    for col in fee_cols:
        # [修正] 使用 pd.to_numeric 先轉數值再填補，解決 FutureWarning
        analysis_df[col] = pd.to_numeric(analysis_df[col], errors='coerce').fillna(0).astype(int)

    # 準備結果容器
    summary_data = []
    exception_details = []

    # 【核心修改 2】依照 (宿舍, 雇主, 特殊狀況) 分組
    grouped = analysis_df.groupby(['宿舍地址', '雇主', '特殊狀況'])

    for (dorm, emp, status), group in grouped:
        group_stats = {
            "宿舍": dorm,
            "雇主": emp,
            "特殊狀況": status, # 新增此欄位
            "總人數": len(group)
        }
        
        for col in fee_cols:
            # 計算眾數 (Mode) 作為 "標準費用"
            modes = group[col].mode()
            standard_fee = modes[0] if not modes.empty else 0
            
            group_stats[f"標準{col}"] = standard_fee
            
            # 找出異常 (費用不等於標準費用的)
            exceptions = group[group[col] != standard_fee]
            
            if not exceptions.empty:
                group_stats[f"{col}異常"] = len(exceptions)
                
                # 記錄異常細節
                for _, row in exceptions.iterrows():
                    exception_details.append({
                        "宿舍": dorm,
                        "雇主": emp,
                        "特殊狀況": status, # 顯示該群組的狀態
                        "姓名": row['姓名'],
                        "房號": row['房號'],
                        "費用項目": col,
                        "標準金額": standard_fee,
                        "實際金額": row[col],
                        # 這裡顯示個人的備註，方便查原因
                        "備註": row.get('個人備註')
                    })
            else:
                group_stats[f"{col}異常"] = 0

        summary_data.append(group_stats)

    summary_df = pd.DataFrame(summary_data)
    exceptions_df = pd.DataFrame(exception_details)

    # --- 4. 顯示彙總表 (儀表板) ---
    st.subheader("📊 收費標準總覽")
    st.info("系統已依據「特殊狀況」自動分組。例如：「掛宿外住」的員工將與「一般」員工分開計算標準費用。")

    if not summary_df.empty:
        # 設定顯示欄位順序 (加入特殊狀況)
        cols_order = ["宿舍", "雇主", "特殊狀況", "總人數"]
        for col in fee_cols:
            cols_order.append(f"標準{col}")
            cols_order.append(f"{col}異常")
        
        # 建立 Column Config
        column_config = {
            "總人數": st.column_config.NumberColumn(format="%d 人"),
            "特殊狀況": st.column_config.TextColumn(help="以此狀態區分收費標準"),
        }
        for col in fee_cols:
            column_config[f"標準{col}"] = st.column_config.NumberColumn(label=f"{col}", format="$%d")
            column_config[f"{col}異常"] = st.column_config.NumberColumn(label="異常", help=f"{col}的異常人數")

        # 顯示表格
        st.dataframe(
            summary_df[cols_order],
            width="stretch",
            hide_index=True,
            column_config=column_config
        )

    # --- 5. 顯示特例細節 ---
    st.markdown("---")
    st.subheader("🔍 特例人員清單")
    
    if exceptions_df.empty:
        st.success("恭喜！所有人員的收費皆符合該宿舍、雇主與狀態的標準。")
    else:
        st.warning(f"共發現 {len(exceptions_df)} 筆收費特例。")
        
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