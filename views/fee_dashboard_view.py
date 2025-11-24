# type: uploaded file
# fileName: cindyhu26/dorm_management_postgresql/dorm_management_postgresql-2c01e357f2dcd360107bbd52dca35c9af17b5156/views/fee_dashboard_view.py

import streamlit as st
import pandas as pd
from datetime import date, timedelta
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

    # 第一列篩選 (宿舍、雇主)
    col1, col2 = st.columns(2)
    selected_dorms = col1.multiselect("篩選宿舍 (預設全部)", options=list(dorm_map.keys()), format_func=lambda x: dorm_map[x])
    selected_employers = col2.multiselect("篩選雇主 (預設全部)", options=employers_list)

    # 【核心修改】第二列篩選 (主要管理人、資料月份區間)
    col3, col4, col5 = st.columns(3)
    
    # 1. 主要管理人篩選
    manager_options = ["全部", "我司", "雇主"]
    selected_manager = col3.selectbox("篩選主要管理人", options=manager_options, index=0)
    
    # 2. 資料月份區間
    data_month_start = col4.date_input("資料月份(起)", value=None, help="篩選「資料月份」的起始範圍")
    data_month_end = col5.date_input("資料月份(迄)", value=None, help="篩選「資料月份」的結束範圍")

    if st.button("🔄 重新整理數據"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    # --- 2. 獲取資料 ---
    filters = {
        "dorm_ids": selected_dorms if selected_dorms else None,
        "employer_names": selected_employers if selected_employers else None,
        # 【核心修改】傳入新參數
        "primary_manager": selected_manager if selected_manager != "全部" else None,
        "data_month_start": data_month_start.strftime('%Y-%m') if data_month_start else None,
        "data_month_end": data_month_end.strftime('%Y-%m') if data_month_end else None
    }

    with st.spinner("正在分析費用結構..."):
        raw_long_df = finance_model.get_dynamic_fee_data_for_dashboard(filters)

    if raw_long_df.empty:
        st.warning("查無符合條件的人員資料。")
        return

    # --- 3. 數據處理核心邏輯 (自動轉置與排序) ---
    
    # 填補基本資料的空值
    raw_long_df['特殊狀況'] = raw_long_df['特殊狀況'].fillna('一般').replace('', '一般')
    raw_long_df['個人備註'] = raw_long_df['個人備註'].fillna('')
    raw_long_df['資料月份'] = raw_long_df['資料月份'].fillna('無紀錄') 
    
    # 日期處理
    raw_long_df['入住日_str'] = raw_long_df['入住日'].apply(lambda x: str(x) if pd.notna(x) else '')

    # Index 定義
    index_cols = ['宿舍地址', '雇主', '姓名', '房號', '特殊狀況', '入住日_str', '個人備註', '資料月份']
    
    # 處理完全無費用紀錄的員工
    raw_long_df['費用類型'] = raw_long_df['費用類型'].fillna('temp_no_fee')
    raw_long_df['金額'] = raw_long_df['金額'].fillna(0)

    # 進行轉置
    analysis_df = raw_long_df.pivot_table(
        index=index_cols, 
        columns='費用類型', 
        values='金額', 
        aggfunc='sum',
        fill_value=0
    ).reset_index()
    
    # 移除暫時的費用欄位
    if 'temp_no_fee' in analysis_df.columns:
        analysis_df.drop(columns=['temp_no_fee'], inplace=True)

    # 取得真實的費用欄位
    raw_fee_cols = [c for c in analysis_df.columns if c not in index_cols]
    
    # 依照設定檔排序
    config = finance_model.get_fee_config()
    ordered_types = config.get("internal_types", [])
    
    def sort_key(col_name):
        if col_name in ordered_types:
            return ordered_types.index(col_name)
        return 999

    fee_cols = sorted(raw_fee_cols, key=sort_key)
    
    # 重組 DataFrame
    final_cols = index_cols + fee_cols
    analysis_df = analysis_df[final_cols]

    # 將日期轉回物件格式
    analysis_df['入住日'] = pd.to_datetime(analysis_df['入住日_str'], errors='coerce').dt.date
    analysis_df.drop(columns=['入住日_str'], inplace=True)

    # --- 4. 進行統計分析 ---
    summary_data = []
    exception_details = []

    if not fee_cols:
        st.info("目前資料庫中沒有任何費用項目的紀錄，以下僅列出人員基本分組。")
        fee_cols = [] 

    # 依照 (宿舍, 雇主, 特殊狀況) 分組
    grouped = analysis_df.groupby(['宿舍地址', '雇主', '特殊狀況', '資料月份'])

    for (dorm, emp, status, month), group in grouped:
        group_stats = {
            "宿舍": dorm,
            "雇主": emp,
            "特殊狀況": status,
            "資料月份": month,
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
                        "特殊狀況": status,
                        "資料月份": month,
                        "姓名": row['姓名'],
                        "房號": row['房號'],
                        "費用項目": col,
                        "標準金額": standard_fee,
                        "實際金額": row[col],
                        "入住日": row['入住日'],
                        "備註": row['個人備註']
                    })
            else:
                group_stats[f"{col}異常"] = 0

        summary_data.append(group_stats)

    summary_df = pd.DataFrame(summary_data)
    exceptions_df = pd.DataFrame(exception_details)

    # --- 5. 顯示彙總表 ---
    st.subheader("📊 收費標準總覽")
    st.info("系統已依據「特殊狀況」與「資料月份」自動分組。")

    if not summary_df.empty:
        cols_order = ["宿舍", "雇主", "特殊狀況", "資料月份", "總人數"]
        column_config = {
            "總人數": st.column_config.NumberColumn(format="%d 人"),
            "特殊狀況": st.column_config.TextColumn(help="以此狀態區分收費標準"),
            "資料月份": st.column_config.TextColumn(help="以此月份為基準進行比較"),
        }
        
        for col in fee_cols:
            cols_order.append(f"標準{col}")
            cols_order.append(f"{col}異常")
            column_config[f"標準{col}"] = st.column_config.NumberColumn(label=f"{col}", format="$%d")
            column_config[f"{col}異常"] = st.column_config.NumberColumn(label="異常", help=f"{col}的異常人數")

        st.dataframe(
            summary_df[cols_order],
            width="stretch",
            hide_index=True,
            column_config=column_config
        )

    # --- 6. 顯示特例人員清單 ---
    st.markdown("---")
    st.subheader("🔍 特例人員清單")
    
    if exceptions_df.empty:
        if fee_cols:
            st.success("恭喜！所有人員的收費皆符合該宿舍、雇主與狀態的標準。")
    else:
        st.warning(f"共發現 {len(exceptions_df)} 筆收費特例。")
        
        # --- 篩選器區塊 ---
        filter_c1, filter_c2 = st.columns(2)
        
        # 1. 費用項目篩選
        filter_ex_col = filter_c1.multiselect("篩選費用項目 (只看這些)", options=fee_cols, default=fee_cols)
        
        # 2. 排除雇主篩選
        ex_employers_list = sorted(exceptions_df['雇主'].unique().tolist())
        exclude_employers = filter_c2.multiselect("排除特定雇主 (不看這些)", options=ex_employers_list)
        
        # --- 3. 入住日區間排除 ---
        st.markdown("##### 進階篩選")
        date_ex_col1, date_ex_col2, date_ex_col3 = st.columns([1, 1, 2])
        enable_date_exclude = date_ex_col1.checkbox("排除特定入住期間", help="勾選此項以排除剛入住或特定時段入住的員工")
        
        date_exclude_start = None
        date_exclude_end = None
        
        if enable_date_exclude:
            default_start = date.today() - timedelta(days=30)
            default_end = date.today()
            date_exclude_start = date_ex_col2.date_input("排除起始日", value=default_start)
            date_exclude_end = date_ex_col3.date_input("排除結束日", value=default_end)

        if filter_ex_col:
            filtered_ex_df = exceptions_df[exceptions_df['費用項目'].isin(filter_ex_col)]
            
            if exclude_employers:
                filtered_ex_df = filtered_ex_df[~filtered_ex_df['雇主'].isin(exclude_employers)]
            
            if enable_date_exclude and date_exclude_start and date_exclude_end:
                if date_exclude_start > date_exclude_end:
                    st.error("排除起始日不能晚於結束日！")
                else:
                    filtered_ex_df = filtered_ex_df[filtered_ex_df['入住日'].notna()]
                    mask = (filtered_ex_df['入住日'] >= date_exclude_start) & (filtered_ex_df['入住日'] <= date_exclude_end)
                    filtered_ex_df = filtered_ex_df[~mask]
                    st.caption(f"已排除 {date_exclude_start} 至 {date_exclude_end} 期間入住的人員。")
            
            st.dataframe(
                filtered_ex_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "標準金額": st.column_config.NumberColumn(format="$%d"),
                    "實際金額": st.column_config.NumberColumn(format="$%d"),
                    "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "資料月份": st.column_config.TextColumn(help="此筆費用的所屬月份"),
                }
            )