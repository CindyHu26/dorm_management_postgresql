import streamlit as st
import pandas as pd
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta 
from data_models import finance_model, dormitory_model, employer_dashboard_model

TOTAL_RENT_TARGET_TYPE = "總收租"
ALL_EMPLOYERS_TARGET = "全部"


def _render_fee_target_editor(dorms_list, employers_list, fee_type_options, filters):
    """顯示並儲存目標價列表，回傳目前啟用中的目標價。"""
    target_df = finance_model.get_fee_target_standards(filters, include_inactive=True)

    dorm_label_by_id = {
        d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}"
        for d in dorms_list
    }
    if not target_df.empty:
        for _, row in target_df.iterrows():
            dorm_id = int(row['dorm_id'])
            if dorm_id not in dorm_label_by_id:
                dorm_label_by_id[dorm_id] = f"({row.get('宿舍編號') or '無編號'}) {row.get('宿舍地址') or ''}"

    dorm_id_by_label = {label: dorm_id for dorm_id, label in dorm_label_by_id.items()}
    dorm_options = list(dorm_id_by_label.keys())
    target_employers = target_df['雇主'].dropna().tolist() if not target_df.empty else []
    target_fee_types = target_df['費用項目'].dropna().tolist() if not target_df.empty else []
    employer_options = list(dict.fromkeys([ALL_EMPLOYERS_TARGET] + sorted(set([e for e in employers_list if e] + target_employers))))
    fee_options = list(dict.fromkeys([TOTAL_RENT_TARGET_TYPE] + [fee for fee in fee_type_options if fee] + target_fee_types))

    with st.expander("🎯 目標價列表（地址 + 雇主）", expanded=not target_df.empty):
        st.caption("設定後，異常分析會優先用這裡的目標金額；費用項目選「總收租」時，目標金額代表單人各項費用合計。")

        if target_df.empty:
            editor_df = pd.DataFrame(columns=["id", "宿舍", "雇主", "費用項目", "目標金額", "啟用", "備註", "刪除"])
        else:
            editor_df = target_df.copy()
            editor_df["宿舍"] = editor_df["dorm_id"].map(dorm_label_by_id)
            missing_label_mask = editor_df["宿舍"].isna()
            if missing_label_mask.any():
                editor_df.loc[missing_label_mask, "宿舍"] = editor_df.loc[missing_label_mask].apply(
                    lambda row: f"({row.get('宿舍編號') or '無編號'}) {row.get('宿舍地址') or ''}", axis=1
                )
            editor_df["刪除"] = False
            editor_df = editor_df[["id", "宿舍", "雇主", "費用項目", "目標金額", "啟用", "備註", "刪除"]]

        edited_df = st.data_editor(
            editor_df,
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            disabled=["id"],
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "宿舍": st.column_config.SelectboxColumn("宿舍地址", options=dorm_options, required=True, width="large"),
                "雇主": st.column_config.SelectboxColumn("雇主", options=employer_options, required=True, width="medium"),
                "費用項目": st.column_config.SelectboxColumn("目標類型", options=fee_options, default=TOTAL_RENT_TARGET_TYPE, required=True, width="small"),
                "目標金額": st.column_config.NumberColumn("目標金額", min_value=0, step=100, format="$%d", required=True),
                "啟用": st.column_config.CheckboxColumn("啟用", default=True),
                "備註": st.column_config.TextColumn("備註", width="medium"),
                "刪除": st.column_config.CheckboxColumn("刪除", default=False),
            },
            key="fee_target_standard_editor",
        )

        if st.button("💾 儲存目標價列表", key="save_fee_target_standards"):
            rows = []
            for _, row in edited_df.iterrows():
                dorm_label = row.get("宿舍")
                employer_value = row.get("雇主")
                if pd.isna(employer_value) or str(employer_value).strip() == "":
                    employer_value = ALL_EMPLOYERS_TARGET
                else:
                    employer_value = str(employer_value).strip()
                rows.append({
                    "id": row.get("id"),
                    "dorm_id": dorm_id_by_label.get(dorm_label),
                    "employer_name": employer_value,
                    "fee_type": row.get("費用項目"),
                    "target_amount": row.get("目標金額"),
                    "active": row.get("啟用", True),
                    "notes": row.get("備註"),
                    "delete": row.get("刪除", False),
                })
            success, message = finance_model.save_fee_target_standards(rows)
            if success:
                st.success(message)
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(message)

    return finance_model.get_fee_target_standards(filters, include_inactive=False)

def render():
    """渲染「費用標準與異常儀表板」"""
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

    # 第二列篩選
    col3, col4, col5 = st.columns(3)
    manager_options = ["全部", "我司", "雇主"]
    selected_manager = col3.selectbox("篩選主要管理人", options=manager_options, index=1)
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
        "primary_manager": selected_manager if selected_manager != "全部" else None,
        "data_month_start": data_month_start.strftime('%Y-%m') if data_month_start else None,
        "data_month_end": data_month_end.strftime('%Y-%m') if data_month_end else None
    }

    config = finance_model.get_fee_config()
    ordered_types = config.get("internal_types", [])
    target_standards_df = _render_fee_target_editor(dorms_list, employers_list, ordered_types, filters)

    with st.spinner("正在分析費用結構..."):
        raw_long_df = finance_model.get_dynamic_fee_data_for_dashboard(filters)

    if raw_long_df.empty:
        st.warning("查無符合條件的人員資料。")
        return

    # --- 3. 數據處理核心邏輯 ---
    if '宿舍編號' not in raw_long_df.columns:
        raw_long_df['宿舍編號'] = '無編號'
    raw_long_df['宿舍編號'] = raw_long_df['宿舍編號'].fillna('無編號').replace('', '無編號')
    raw_long_df['特殊狀況'] = raw_long_df['特殊狀況'].fillna('一般').replace('', '一般')
    raw_long_df['個人備註'] = raw_long_df['個人備註'].fillna('')
    raw_long_df['資料月份'] = raw_long_df['資料月份'].fillna('無紀錄') 
    raw_long_df['入住日_str'] = raw_long_df['入住日'].apply(lambda x: str(x) if pd.notna(x) else '')

    index_cols = ['宿舍ID', '宿舍編號', '宿舍地址', '雇主', '姓名', '房號', '特殊狀況', '入住日_str', '個人備註', '資料月份']
    raw_long_df['費用類型'] = raw_long_df['費用類型'].fillna('temp_no_fee')
    raw_long_df['金額'] = raw_long_df['金額'].fillna(0)

    analysis_df = raw_long_df.pivot_table(
        index=index_cols, columns='費用類型', values='金額', aggfunc='sum', fill_value=0
    ).reset_index()
    
    if 'temp_no_fee' in analysis_df.columns:
        analysis_df.drop(columns=['temp_no_fee'], inplace=True)

    raw_fee_cols = [c for c in analysis_df.columns if c not in index_cols]
    target_fee_cols = []
    if not target_standards_df.empty:
        target_fee_cols = target_standards_df.loc[target_standards_df['費用項目'] != TOTAL_RENT_TARGET_TYPE, '費用項目'].dropna().astype(str).tolist()

    all_fee_cols = list(dict.fromkeys(raw_fee_cols + target_fee_cols))
    for fee_col in all_fee_cols:
        if fee_col not in analysis_df.columns:
            analysis_df[fee_col] = 0

    def sort_key(col_name):
        return ordered_types.index(col_name) if col_name in ordered_types else 999
    fee_cols = sorted(all_fee_cols, key=sort_key)
    
    final_cols = index_cols + fee_cols
    analysis_df = analysis_df[final_cols]
    analysis_df['入住日'] = pd.to_datetime(analysis_df['入住日_str'], errors='coerce').dt.date
    analysis_df.drop(columns=['入住日_str'], inplace=True)

    # --- 4. 進行統計分析 ---
    summary_data = []
    exception_details = []

    if not fee_cols:
        st.info("目前資料庫中沒有任何費用項目的紀錄。")
        fee_cols = [] 

    active_target_standards = target_standards_df[target_standards_df['啟用'].fillna(False)] if not target_standards_df.empty else pd.DataFrame()
    target_lookup = {}
    if not active_target_standards.empty:
        per_item_target_standards = active_target_standards[active_target_standards['費用項目'] != TOTAL_RENT_TARGET_TYPE]
        for _, target_row in per_item_target_standards.iterrows():
            target_lookup[(int(target_row['dorm_id']), str(target_row['雇主']), str(target_row['費用項目']))] = int(target_row['目標金額'])

    # 預先計算「宿舍層級」的標準 (Fallback 機制)
    dorm_level_standards = {}
    analysis_df['total_fee'] = analysis_df[fee_cols].sum(axis=1)
    
    total_target_gap_df = pd.DataFrame()
    total_target_rows = active_target_standards[active_target_standards['費用項目'] == TOTAL_RENT_TARGET_TYPE] if not active_target_standards.empty else pd.DataFrame()
    total_target_lookup = {}
    if not total_target_rows.empty:
        for _, target_row in total_target_rows.iterrows():
            employer = str(target_row['雇主']).strip() if pd.notna(target_row['雇主']) else ALL_EMPLOYERS_TARGET
            if not employer:
                employer = ALL_EMPLOYERS_TARGET
            total_target_lookup[(int(target_row['dorm_id']), employer)] = {
                "amount": int(target_row['目標金額']),
                "notes": "" if pd.isna(target_row.get('備註', '')) else str(target_row.get('備註', '')).strip(),
            }

    # 計算各費用項目的宿舍標準
    for col in fee_cols:
        valid_fees = analysis_df[analysis_df[col] > 0]
        if not valid_fees.empty:
            dorm_modes = valid_fees.groupby(['宿舍地址', '特殊狀況'])[col].apply(lambda x: x.mode().iloc[0] if not x.mode().empty else 0)
            dorm_level_standards[col] = dorm_modes.to_dict()
            
    # 預先計算「宿舍層級」的總標準
    dorm_level_total_standards = {}
    valid_totals = analysis_df[analysis_df['total_fee'] > 0]
    if not valid_totals.empty:
        dorm_total_modes = valid_totals.groupby(['宿舍地址', '特殊狀況'])['total_fee'].apply(lambda x: x.mode().iloc[0] if not x.mode().empty else 0)
        dorm_level_total_standards = dorm_total_modes.to_dict()

    grouped = analysis_df.groupby(['宿舍ID', '宿舍編號', '宿舍地址', '雇主', '特殊狀況', '資料月份'])

    for (dorm_id, dorm_code, dorm, emp, status, month), group in grouped:
        group_stats = {
            "宿舍編號": dorm_code, "宿舍": dorm, "雇主": emp, "特殊狀況": status, "資料月份": month, "總人數": len(group), "有目標差異": False
        }
        
        # 1. 計算該群組各費用項目的標準金額
        group_standards = {}
        group_standard_sources = {}
        for col in fee_cols:
            modes = group[col].mode()
            local_standard = modes[0] if not modes.empty else 0
            inferred_standard = local_standard
            inferred_source = "群組推算"
            if local_standard == 0:
                dorm_standard = dorm_level_standards.get(col, {}).get((dorm, status), 0)
                if dorm_standard > 0:
                    inferred_standard = dorm_standard
                    inferred_source = "宿舍推算"

            if status == "掛宿外住(不收費)":
                inferred_standard = 0
                inferred_source = "特殊狀況"

            target_standard = target_lookup.get((int(dorm_id), str(emp), str(col)))
            if target_standard is None:
                target_standard = target_lookup.get((int(dorm_id), ALL_EMPLOYERS_TARGET, str(col)))
            if target_standard is not None:
                effective_standard = target_standard
                standard_source = "目標價"
                target_diff = target_standard - inferred_standard
                if target_diff != 0:
                    group_stats["有目標差異"] = True
            else:
                effective_standard = inferred_standard
                standard_source = inferred_source
                target_diff = None

            group_standards[col] = effective_standard
            group_standard_sources[col] = standard_source
            group_stats[f"標準{col}"] = effective_standard
            group_stats[f"群組推算{col}"] = inferred_standard
            group_stats[f"{col}目標差異"] = target_diff
            group_stats[f"{col}來源"] = standard_source
        group_total_series = group['total_fee']
        modes = group_total_series.mode()
        total_local_standard = modes[0] if not modes.empty else 0
        inferred_total_standard = total_local_standard
        if total_local_standard == 0:
            inferred_total_standard = dorm_level_total_standards.get((dorm, status), 0)
        if status == "掛宿外住(不收費)":
            inferred_total_standard = 0

        # 例外清單仍用有效基準加總；總收租目標差異則固定比對單人總額推算值。
        if any(source == "目標價" for source in group_standard_sources.values()):
            total_standard = sum(group_standards.values())
        else:
            total_standard = inferred_total_standard

        total_target_info = total_target_lookup.get((int(dorm_id), str(emp)))
        if total_target_info is None:
            total_target_info = total_target_lookup.get((int(dorm_id), ALL_EMPLOYERS_TARGET))

        group_stats["群組推算總收租"] = inferred_total_standard
        if total_target_info:
            total_target_amount = total_target_info["amount"]
            total_target_diff = total_target_amount - inferred_total_standard
            group_stats["目標總收租"] = total_target_amount
            group_stats["總收租目標差異"] = total_target_diff
            group_stats["目標價備註"] = total_target_info["notes"]
            if total_target_diff != 0:
                group_stats["有目標差異"] = True
        else:
            group_stats["目標總收租"] = None
            group_stats["總收租目標差異"] = None
            group_stats["目標價備註"] = ""
            
        # 2. 比對異常並記錄
        for col in fee_cols:
            effective_standard = group_standards[col]
            exceptions = group[group[col] != effective_standard]
            if not exceptions.empty:
                group_stats[f"{col}異常"] = len(exceptions)
                for _, row in exceptions.iterrows():
                    person_total_actual = sum(row[c] for c in fee_cols)
                    exception_details.append({
                        "宿舍編號": dorm_code, "宿舍": dorm, "雇主": emp, "特殊狀況": status, "資料月份": month,
                        "姓名": row['姓名'], "房號": row['房號'], "費用項目": col,
                        "標準金額": effective_standard, "實際金額": row[col],
                        "差額": row[col] - effective_standard,
                        "基準來源": group_standard_sources[col],
                        "總標準金額": total_standard,
                        "總實際金額": person_total_actual,
                        "入住日": row['入住日'], "備註": row['個人備註']
                    })
            else:
                group_stats[f"{col}異常"] = 0
        summary_data.append(group_stats)

    summary_df = pd.DataFrame(summary_data)
    exceptions_df = pd.DataFrame(exception_details)

    if not summary_df.empty and "目標總收租" in summary_df.columns:
        target_summary_df = summary_df[summary_df["目標總收租"].notna()].copy()
        if not target_summary_df.empty:
            target_summary_df["判斷"] = target_summary_df["總收租目標差異"].fillna(0).apply(lambda diff: "符合" if diff == 0 else "有差距")
            total_target_gap_df = target_summary_df[[
                "宿舍編號", "宿舍", "雇主", "特殊狀況", "資料月份", "總人數",
                "群組推算總收租", "目標總收租", "總收租目標差異", "判斷", "目標價備註"
            ]]

    # --- 5. 顯示單人總收租目標差異 ---
    if not total_target_gap_df.empty:
        st.subheader("🎯 單人總收租目標差異")
        gap_view_df = total_target_gap_df.sort_values(by=['判斷', '宿舍編號', '宿舍', '雇主', '資料月份'], ascending=[True, True, True, True, True])
        st.dataframe(
            gap_view_df,
            width="stretch",
            hide_index=True,
            column_config={
                "總人數": st.column_config.NumberColumn(format="%d 人"),
                "群組推算總收租": st.column_config.NumberColumn(format="$%d", help="單人各項費用合計的推算標準"),
                "目標總收租": st.column_config.NumberColumn(format="$%d", help="目標價列表設定的單人總額"),
                "總收租目標差異": st.column_config.NumberColumn(format="$%d", help="目標總收租 - 群組推算總收租"),
            },
        )

    # --- 6. 顯示彙總表 ---
    st.subheader("📊 收費標準總覽")
    st.info("系統已依據「特殊狀況」與「資料月份」自動分組。若某雇主標準為0，系統會自動參照同宿舍其他雇主的標準。")

    if not summary_df.empty:
        show_target_diff_only = st.checkbox(
            "只顯示目標價與群組推算有差異的組合",
            value=False,
            help="只保留已設定目標價，且目標價與系統推算標準不同的宿舍/雇主組合。"
        )
        display_summary_df = summary_df.copy()
        if show_target_diff_only:
            display_summary_df = display_summary_df[display_summary_df['有目標差異']]

        cols_order = ["宿舍編號", "宿舍", "雇主", "特殊狀況", "資料月份", "總人數", "群組推算總收租", "目標總收租", "總收租目標差異", "目標價備註"]
        column_config = {
            "總人數": st.column_config.NumberColumn(format="%d 人"),
            "特殊狀況": st.column_config.TextColumn(help="以此狀態區分收費標準"),
            "資料月份": st.column_config.TextColumn(help="以此月份為基準進行比較"),
            "群組推算總收租": st.column_config.NumberColumn(format="$%d"),
            "目標總收租": st.column_config.NumberColumn(format="$%d"),
            "總收租目標差異": st.column_config.NumberColumn(format="$%d", help="目標總收租 - 群組推算總收租"),
            "目標價備註": st.column_config.TextColumn(help="目標價列表中的備註"),
        }
        for col in fee_cols:
            cols_order.append(f"標準{col}")
            cols_order.append(f"群組推算{col}")
            cols_order.append(f"{col}來源")
            cols_order.append(f"{col}異常")
            column_config[f"標準{col}"] = st.column_config.NumberColumn(label=f"{col}", format="$%d")
            column_config[f"群組推算{col}"] = st.column_config.NumberColumn(label="群組推算", format="$%d")
            column_config[f"{col}來源"] = st.column_config.TextColumn(label="來源")
            column_config[f"{col}異常"] = st.column_config.NumberColumn(label="異常", help=f"{col}的異常人數")

        if display_summary_df.empty:
            st.info("目前沒有目標價與群組推算不同的組合。")
        else:
            st.dataframe(display_summary_df[cols_order], width="stretch", hide_index=True, column_config=column_config)
    # --- 7. 顯示特例人員清單 ---
    st.markdown("---")
    st.subheader("🔍 特例人員清單")
    
    if exceptions_df.empty:
        if fee_cols: st.success("恭喜！所有人員的收費皆符合該宿舍、雇主與狀態的標準。")
    else:
        st.warning(f"共發現 {len(exceptions_df)} 筆收費特例。")
        
        # --- 篩選器區塊 ---
        st.markdown("##### 🎯 快速篩選")
        show_potential_missing = st.checkbox(
            "🚨 只顯示「入住超過 1 個完整月且無費用 (金額=0)」的異常", 
            help="篩選邏輯：入住日早於「上個月1號」。例如現在11月，會抓出9/30(含)以前入住，但至今無費用紀錄的人。"
        )
        exclude_same_total = st.checkbox(
            "💡 排除「總金額相符」的異常",
            value=True,
            help="若勾選，當該員工各項費用加總的「總實際金額」與「總標準金額」相同時(僅收費名目不同)，將不會顯示在清單中。"
        )

        st.markdown("##### 進階篩選")
        filter_c1, filter_c2 = st.columns(2)
        filter_ex_col = filter_c1.multiselect("篩選費用項目 (只看這些)", options=fee_cols, default=fee_cols)
        ex_employers_list = sorted(exceptions_df['雇主'].unique().tolist())
        exclude_employers = filter_c2.multiselect("排除特定雇主 (不看這些)", options=ex_employers_list)
        
        date_ex_col1, date_ex_col2, date_ex_col3 = st.columns([1, 1, 2])
        enable_date_exclude = date_ex_col1.checkbox("手動排除入住期間", help="勾選此項以排除剛入住或特定時段入住的員工")
        date_exclude_start = None
        date_exclude_end = None
        if enable_date_exclude:
            default_start = date.today() - timedelta(days=30)
            default_end = date.today()
            date_exclude_start = date_ex_col2.date_input("排除起始日", value=default_start)
            date_exclude_end = date_ex_col3.date_input("排除結束日", value=default_end)

        # --- 執行篩選邏輯 ---
        filtered_ex_df = exceptions_df.copy()

        # 1. 快速篩選：潛在漏收租
        if show_potential_missing:
            # 計算截止日：上個月1號
            cutoff_date = date.today().replace(day=1) - relativedelta(months=1)
            
            filtered_ex_df = filtered_ex_df[
                (filtered_ex_df['入住日'].notna()) &                 
                (filtered_ex_df['入住日'] < cutoff_date) &          
                (filtered_ex_df['實際金額'] == 0) &                 
                (filtered_ex_df['標準金額'] > 0)                    
            ]
            if filtered_ex_df.empty:
                st.success(f"太棒了！沒有發現「入住日早於 {cutoff_date} 且漏收費用」的異常人員。")
                
        # 1.5 排除總金額相符
        if exclude_same_total:
            filtered_ex_df = filtered_ex_df[filtered_ex_df['總實際金額'] != filtered_ex_df['總標準金額']]

        # 2. 費用項目篩選
        if filter_ex_col:
            filtered_ex_df = filtered_ex_df[filtered_ex_df['費用項目'].isin(filter_ex_col)]
        
        # 3. 排除雇主
        if exclude_employers:
            filtered_ex_df = filtered_ex_df[~filtered_ex_df['雇主'].isin(exclude_employers)]
        
        # 4. 手動日期排除 (若開啟)
        if not show_potential_missing and enable_date_exclude and date_exclude_start and date_exclude_end:
            if date_exclude_start > date_exclude_end:
                st.error("排除起始日不能晚於結束日！")
            else:
                filtered_ex_df = filtered_ex_df[filtered_ex_df['入住日'].notna()]
                mask = (filtered_ex_df['入住日'] >= date_exclude_start) & (filtered_ex_df['入住日'] <= date_exclude_end)
                filtered_ex_df = filtered_ex_df[~mask]
                st.caption(f"已排除 {date_exclude_start} 至 {date_exclude_end} 期間入住的人員。")
        
        if not filtered_ex_df.empty:
            st.dataframe(
                filtered_ex_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "標準金額": st.column_config.NumberColumn(format="$%d"),
                    "實際金額": st.column_config.NumberColumn(format="$%d"),
                    "差額": st.column_config.NumberColumn(format="$%d"),
                    "基準來源": st.column_config.TextColumn(),
                    "總標準金額": st.column_config.NumberColumn(format="$%d"),
                    "總實際金額": st.column_config.NumberColumn(format="$%d"),
                    "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "資料月份": st.column_config.TextColumn(help="此筆費用的所屬月份"),
                }
            )