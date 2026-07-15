# views/employer_dashboard_view.py

import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import employer_dashboard_model, dormitory_model
from views.report_view import to_excel 

def generate_html_report(title, kpi_data, summary_df, resident_summary_df, details_data, custom_cols=None):
    """
    生成適合列印的 HTML 報表。
    """
    # 1. CSS 樣式
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <style>
            body {{ font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; font-size: 12px; padding: 20px; }}
            h1 {{ text-align: center; font-size: 22px; margin-bottom: 5px; }}
            h2 {{ text-align: center; font-size: 14px; color: #555; margin-bottom: 20px; }}
            h3 {{ border-left: 5px solid #4CAF50; padding-left: 10px; margin-top: 25px; margin-bottom: 10px; font-size: 16px; page-break-after: avoid; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; font-size: 11px; }}
            th, td {{ border: 1px solid #ddd; padding: 6px; text-align: right; }}
            th {{ background-color: #f8f9fa; text-align: center; font-weight: bold; color: #333; }}
            .text-left {{ text-align: left; }}
            .center {{ text-align: center; }}
            .kpi-container {{ display: flex; justify-content: space-between; margin-bottom: 20px; border: 1px solid #ddd; padding: 10px; border-radius: 4px; background-color: #fff; }}
            .kpi-box {{ text-align: center; flex: 1; border-right: 1px solid #eee; }}
            .kpi-box:last-child {{ border-right: none; }}
            .kpi-label {{ font-size: 12px; color: #666; }}
            .kpi-value {{ font-size: 16px; font-weight: bold; margin-top: 4px; }}
            .profit-pos {{ color: #28a745; }}
            .profit-neg {{ color: #dc3545; }}
            .total-row {{ font-weight: bold; background-color: #e8f5e9 !important; }}
            @media print {{
                @page {{ size: A4; margin: 1cm; }}
                body {{ padding: 0; }}
                .no-print {{ display: none; }}
                .page-break {{ page-break-before: always; }}
                .avoid-break {{ page-break-inside: avoid; }}
            }}
        </style>
    </head>
    <body>
        <h1>雇主損益分析報表</h1>
        <h2>{title}</h2>
    """

    # 2. KPI 摘要
    profit_color = "profit-pos" if kpi_data['profit'] >= 0 else "profit-neg"
    html += f"""
        <div class="kpi-container">
            <div class="kpi-box">
                <div class="kpi-label">總在住人數 (期間/年)</div>
                <div class="kpi-value">{kpi_data['headcount']} 人</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-label">總收入</div>
                <div class="kpi-value">NT$ {kpi_data['income']:,}</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-label">總支出 (我司)</div>
                <div class="kpi-value">NT$ {kpi_data['expense']:,}</div>
            </div>
            <div class="kpi-box">
                <div class="kpi-label">淨損益</div>
                <div class="kpi-value {profit_color}">NT$ {kpi_data['profit']:,}</div>
            </div>
        </div>
    """

    # 3. 損益總表
    html += "<h3>💰 各宿舍損益總表</h3>"
    html += "<table><thead><tr>"
    
    if custom_cols:
        cols = custom_cols
    else:
        cols = ["宿舍地址", "在住人數", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
    
    for c in cols:
        html += f"<th>{c}</th>"
    html += "</tr></thead><tbody>"
    
    for _, row in summary_df.iterrows():
        is_total = row.get('宿舍地址') == '總計'
        row_class = "total-row" if is_total else ""
        html += f"<tr class='{row_class}'>"
        for c in cols:
            val = row.get(c, 0)
            display_val = val
            if isinstance(val, (int, float)):
                display_val = f"{int(val):,}"
            align_class = "text-left" if c == "宿舍地址" else ""
            html += f"<td class='{align_class}'>{display_val}</td>"
        html += "</tr>"
    html += "</tbody></table>"

    # 4. 住宿統計 (若有)
    if resident_summary_df is not None and not resident_summary_df.empty:
        html += "<h3>👥 各宿舍住宿人數統計</h3>"
        html += "<table><thead><tr>"
        res_cols = [c for c in resident_summary_df.columns if c != '主要管理人']
        for c in res_cols:
            html += f"<th>{c}</th>"
        html += "</tr></thead><tbody>"
        
        for _, row in resident_summary_df.iterrows():
            html += "<tr>"
            for c in res_cols:
                val = row[c]
                align = "text-left" if isinstance(val, str) and not val.replace(",","").replace(".","").isnumeric() else ""
                html += f"<td class='{align}'>{val}</td>"
            html += "</tr>"
        html += "</tbody></table>"

    # 5. 詳細收支
    html += "<h3>📝 各宿舍收支明細 (財務細項)</h3>"
    has_details = False
    for dorm_name, details in details_data.items():
        inc_df, exp_df = details
        if inc_df.empty and exp_df.empty: continue
        has_details = True
        html += f"<div class='avoid-break' style='margin-bottom: 15px; border: 1px solid #eee; padding: 10px;'>"
        html += f"<div style='font-weight:bold; font-size:13px; margin-bottom:5px; color:#333;'>🏠 {dorm_name}</div>"
        html += "<table style='width:100%; border:none; margin:0;'><tr>"
        html += "<td style='vertical-align:top; border:none; width:50%; padding:0 5px 0 0;'>"
        if not inc_df.empty:
            html += "<div style='border-bottom:1px solid #ddd; margin-bottom:3px; color:green;'>收入項目</div>"
            for _, row in inc_df.iterrows():
                html += f"<div style='display:flex; justify-content:space-between;'><span>{row['項目']}</span><span>${int(row['金額']):,}</span></div>"
        else: html += "<div style='color:#999;'>無收入明細</div>"
        html += "</td>"
        html += "<td style='vertical-align:top; border:none; width:50%; padding:0 0 0 5px; border-left:1px solid #eee;'>"
        if not exp_df.empty:
            html += "<div style='border-bottom:1px solid #ddd; margin-bottom:3px; color:red;'>支出項目 (分攤後)</div>"
            for _, row in exp_df.iterrows():
                html += f"<div style='display:flex; justify-content:space-between;'><span>{row['費用項目']}</span><span>${int(row['分攤後金額']):,}</span></div>"
        else: html += "<div style='color:#999;'>無支出明細</div>"
        html += "</td></tr></table></div>"

    html += """
        <div class="center no-print" style="margin-top: 30px; color: #999; font-size: 10px;">--- 報表結束 ---</div>
    </body></html>
    """
    return html

def render():
    """渲染「雇主儀表板」頁面"""
    st.info("請從下方選擇一位或多位雇主，以檢視其所有在住員工的詳細住宿分佈與財務貢獻情況。")

    @st.cache_data
    def get_employers_list():
        return employer_dashboard_model.get_all_employers()

    employers_list = get_employers_list()
    if not employers_list:
        st.warning("目前資料庫中沒有任何員工資料可供查詢。")
        return

    selected_employers = st.multiselect("請選擇要分析的雇主 (可多選)：", options=employers_list)
    if st.button("🔄 重新整理所有數據"): st.cache_data.clear()
    st.markdown("---")

    if selected_employers:
        only_my_company = st.checkbox("只顯示「我司管理」的宿舍", value=False)
        
        @st.cache_data
        def get_dorm_id_map():
            all_dorms = dormitory_model.get_dorms_for_selection()
            return {d['original_address']: d['id'] for d in all_dorms}
        dorm_id_map = get_dorm_id_map()

        tab1, tab2, tab3 = st.tabs(["📊 按月檢視 (攤提)", "📅 年度總覽 (攤提)", "💸 現金流分析 (不攤提)"])

        # ==============================================================================
        # 頁籤 1: 按月檢視
        # ==============================================================================
        with tab1:
            st.subheader("每月財務與住宿分析")
            today = datetime.now()
            default_date = today - relativedelta(months=2)
            year_options = list(range(today.year - 2, today.year + 2))
            c1, c2 = st.columns(2)
            selected_year_month = c1.selectbox("選擇年份", options=year_options, index=2, key="monthly_year")
            selected_month_month = c2.selectbox("選擇月份", options=range(1, 13), index=default_date.month - 1, key="monthly_month")
            year_month_str = f"{selected_year_month}-{selected_month_month:02d}"

            @st.cache_data
            def get_finance_summary(employers, period, only_mc):
                return employer_dashboard_model.get_employer_financial_summary(employers, period, only_mc)
            finance_df_month = get_finance_summary(selected_employers, year_month_str, only_my_company)

            @st.cache_data
            def get_details_for_period(employers, period, only_mc):
                return employer_dashboard_model.get_employer_resident_details(employers, period, only_mc)
            report_df_month = get_details_for_period(selected_employers, year_month_str, only_my_company)

            if finance_df_month.empty:
                st.warning(f"在 {year_month_str} 中，找不到與所選雇主相關的收支紀錄。")
            else:
                finance_df_month['總收入'] = finance_df_month['收入(員工月費)'] + finance_df_month['分攤其他收入']
                total_income = finance_df_month['總收入'].sum()
                total_expense_by_us = finance_df_month['我司分攤合約費'].sum() + finance_df_month['我司分攤雜費'].sum() + finance_df_month['我司分攤攤銷'].sum()
                profit_loss = total_income - total_expense_by_us

                st.markdown(f"#### {year_month_str} 財務總覽")
                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("總收入", f"NT$ {total_income:,.0f}")
                f_col2.metric("我司分攤總支出", f"NT$ {total_expense_by_us:,.0f}")
                f_col3.metric("淨貢獻", f"NT$ {profit_loss:,.0f}", delta=f"{profit_loss:,.0f}")

                display_df = finance_df_month.copy()
                display_df['淨損益'] = (display_df['收入(員工月費)'] + display_df['分攤其他收入']) - (display_df['我司分攤合約費'] + display_df['我司分攤雜費'] + display_df['我司分攤攤銷'])
                
                if not report_df_month.empty:
                    dorm_headcounts = report_df_month.groupby('宿舍地址').size().reset_index(name='在住人數')
                    display_df = pd.merge(display_df, dorm_headcounts, on='宿舍地址', how='left')
                    display_df['在住人數'] = display_df['在住人數'].fillna(0).astype(int)
                else:
                    display_df['在住人數'] = 0
                total_headcount = display_df['在住人數'].sum()

                cols_to_sum = ["在住人數", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                sum_row = display_df[cols_to_sum].sum()
                sum_row['宿舍地址'] = '總計'
                for col in display_df.columns:
                    if col not in sum_row: sum_row[col] = "" 
                display_df_with_total = pd.concat([display_df, pd.DataFrame([sum_row])], ignore_index=True)

                st.markdown("##### 各宿舍收支詳情 (所選雇主)")
                cols_to_display = ["宿舍地址", "在住人數", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                cols_exist = [col for col in cols_to_display if col in display_df_with_total.columns]
                
                st.dataframe(
                    display_df_with_total[cols_exist], width='stretch', hide_index=True,
                    column_config={c: st.column_config.NumberColumn(format="NT$ %d") for c in cols_exist if c not in ["宿舍地址", "在住人數"]}
                )

                dorm_summary_df = pd.DataFrame()
                if not report_df_month.empty:
                    grouped = report_df_month.groupby(['宿舍地址', '主要管理人'])
                    summary_df = grouped.agg(總人數=('姓名', 'count'), 男性=('性別', lambda s: (s=='男').sum()), 女性=('性別', lambda s: (s=='女').sum()))
                    def create_dist_str(series): s = series.dropna(); return "" if s.empty else ", ".join([f"{i}:{c}" for i, c in s.value_counts().items()])
                    nationality_df = grouped['國籍'].apply(create_dist_str).rename('國籍分佈')
                    status_df = grouped['特殊狀況'].apply(lambda s: create_dist_str(s[s.str.strip()!=''])).rename('特殊狀況')
                    dorm_summary_df = pd.concat([summary_df, nationality_df, status_df], axis=1).reset_index()
                    st.markdown("---"); st.markdown("##### 住宿人員統計"); st.dataframe(dorm_summary_df, width='stretch', hide_index=True)

                # 匯出
                st.markdown("---"); st.write("🖨️ **報表輸出**")
                col_export_html, col_export_excel = st.columns(2)
                emp_names_str = "_".join(selected_employers)[:15]
                title_str = f"{emp_names_str} ({year_month_str})"
                all_details_dict = {} 
                all_details_list_excel = []

                with st.spinner("正在準備詳細資料..."):
                    for _, row in display_df.iterrows():
                        d_addr = row['宿舍地址']; d_id = dorm_id_map.get(d_addr)
                        if d_id:
                            inc, exp = employer_dashboard_model.get_employer_financial_details_for_dorm(selected_employers, d_id, year_month_str)
                            all_details_dict[d_addr] = (inc, exp)
                            if not inc.empty:
                                inc['宿舍'] = d_addr; inc['類別'] = '收入'; inc = inc.rename(columns={'項目': '細項', '金額': '金額'})
                                all_details_list_excel.append(inc[['宿舍', '類別', '細項', '金額']])
                            if not exp.empty:
                                exp['宿舍'] = d_addr; exp['類別'] = '支出'; exp = exp.rename(columns={'費用項目': '細項', '分攤後金額': '金額'})
                                all_details_list_excel.append(exp[['宿舍', '類別', '細項', '金額']])

                kpi_data = { "headcount": total_headcount, "income": int(total_income), "expense": int(total_expense_by_us), "profit": int(profit_loss) }
                html_content = generate_html_report(title_str, kpi_data, display_df_with_total, dorm_summary_df, all_details_dict, cols_exist)
                col_export_html.download_button("📄 下載列印報表 (HTML)", html_content, file_name=f"Report_{year_month_str}.html", mime="text/html")

                summary_sheet = display_df_with_total[cols_exist].copy()
                details_sheet = pd.concat(all_details_list_excel, ignore_index=True) if all_details_list_excel else pd.DataFrame(columns=['宿舍', '類別', '細項', '金額'])
                excel_data = to_excel({ "損益總表": [{"dataframe": summary_sheet, "title": f"雇主損益總表 - {title_str}"}], "住宿統計": [{"dataframe": dorm_summary_df, "title": "住宿人數統計"}] if not dorm_summary_df.empty else [], "詳細收支": [{"dataframe": details_sheet, "title": "各宿舍收支明細"}] })
                col_export_excel.download_button("📊 下載 Excel", excel_data, file_name=f"Report_{year_month_str}.xlsx")

                st.markdown("---")
                with st.expander("查看員工詳細名單 (螢幕檢視用)"):
                    if not report_df_month.empty:
                        columns_to_show = ["宿舍地址", "房號", "姓名", "性別", "國籍", "入住日", "離住日", "員工月費", "特殊狀況", "雇主"]
                        existing_columns = [col for col in columns_to_show if col in report_df_month.columns]
                        st.dataframe(report_df_month[existing_columns], width='stretch', hide_index=True, column_config={ "員工月費": st.column_config.NumberColumn(format="NT$ %d"), "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"), "離住日": st.column_config.DateColumn(format="YYYY-MM-DD") })
                    else: st.info("無詳細名單。")

        # ==============================================================================
        # 頁籤 2: 年度總覽
        # ==============================================================================
        with tab2:
            st.subheader("年度財務總覽")
            selected_year_annual = st.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="annual_year")

            @st.cache_data
            def get_finance_summary_annual(employers, year, only_mc):
                return employer_dashboard_model.get_employer_financial_summary_annual(employers, year, only_mc)
            finance_df_annual = get_finance_summary_annual(selected_employers, selected_year_annual, only_my_company)

            if finance_df_annual.empty:
                st.warning(f"在 {selected_year_annual} 年中，找不到與所選雇主相關的收支紀錄。")
            else:
                finance_df_annual['總收入'] = finance_df_annual['收入(員工月費)'] + finance_df_annual['分攤其他收入']
                total_income_annual = finance_df_annual['總收入'].sum()
                total_expense_by_us_annual = finance_df_annual['我司分攤合約費'].sum() + finance_df_annual['我司分攤雜費'].sum() + finance_df_annual['我司分攤攤銷'].sum()
                profit_loss_annual = total_income_annual - total_expense_by_us_annual

                st.markdown(f"#### {selected_year_annual} 年度財務總覽")
                fa_col1, fa_col2, fa_col3 = st.columns(3)
                fa_col1.metric("年度總收入", f"NT$ {total_income_annual:,.0f}")
                fa_col2.metric("年度我司分攤總支出", f"NT$ {total_expense_by_us_annual:,.0f}")
                fa_col3.metric("年度淨貢獻", f"NT$ {profit_loss_annual:,.0f}", delta=f"{profit_loss_annual:,.0f}")

                display_df_annual = finance_df_annual.copy()
                display_df_annual['淨損益'] = (display_df_annual['收入(員工月費)'] + display_df_annual['分攤其他收入']) - (display_df_annual['我司分攤合約費'] + display_df_annual['我司分攤雜費'] + display_df_annual['我司分攤攤銷'])
                
                # 使用 SQL 回傳的「在住人數(年)」
                total_headcount_annual = display_df_annual['在住人數(年)'].sum() if '在住人數(年)' in display_df_annual.columns else 0

                # 【修改】加入「目前人數」
                total_current_headcount = display_df_annual['目前人數'].sum() if '目前人數' in display_df_annual.columns else 0

                cols_to_sum_annual = ["在住人數(年)", "目前人數", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                # 確保欄位存在
                existing_cols_to_sum = [c for c in cols_to_sum_annual if c in display_df_annual.columns]
                sum_row_annual = display_df_annual[existing_cols_to_sum].sum()
                
                sum_row_annual['宿舍地址'] = '總計'
                for col in display_df_annual.columns:
                    if col not in sum_row_annual: sum_row_annual[col] = ""
                
                display_df_annual_with_total = pd.concat([display_df_annual, pd.DataFrame([sum_row_annual])], ignore_index=True)

                # 【修改】顯示順序加入「目前人數」
                cols_to_display_annual = ["宿舍地址", "在住人數(年)", "目前人數", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                cols_exist_annual = [col for col in cols_to_display_annual if col in display_df_annual_with_total.columns]

                st.dataframe(
                    display_df_annual_with_total[cols_exist_annual], width='stretch', hide_index=True,
                    column_config={
                        col: st.column_config.NumberColumn(format="NT$ %d") for col in cols_exist_annual 
                        if col not in ["宿舍地址", "在住人數(年)", "目前人數"]
                    }
                )
                
                # 匯出 (年度)
                st.markdown("---"); st.write("🖨️ **報表輸出**")
                eac1, eac2 = st.columns(2)
                emp_str = "_".join(selected_employers)[:10]
                title_ann = f"{emp_str} 年度報表 ({selected_year_annual})"

                # 準備詳細 (年度)
                ann_details_dict = {}
                ann_details_list = []
                with st.spinner("準備資料中..."):
                    for _, row in display_df_annual.iterrows():
                        d_addr = row['宿舍地址']; d_id = dorm_id_map.get(d_addr)
                        if d_id:
                            inc, exp = employer_dashboard_model.get_employer_financial_details_for_dorm(selected_employers, d_id, str(selected_year_annual))
                            ann_details_dict[d_addr] = (inc, exp)
                            if not inc.empty:
                                inc['宿舍'] = d_addr; inc['類別'] = '收入'; inc = inc.rename(columns={'項目': '細項', '金額': '金額'})
                                ann_details_list.append(inc[['宿舍', '類別', '細項', '金額']])
                            if not exp.empty:
                                exp['宿舍'] = d_addr; exp['類別'] = '支出'; exp = exp.rename(columns={'費用項目': '細項', '分攤後金額': '金額'})
                                ann_details_list.append(exp[['宿舍', '類別', '細項', '金額']])

                # HTML
                kpi_ann = { "headcount": total_headcount_annual, "income": int(total_income_annual), "expense": int(total_expense_by_us_annual), "profit": int(profit_loss_annual) }
                html_ann = generate_html_report(title_ann, kpi_ann, display_df_annual_with_total, None, ann_details_dict, cols_exist_annual)
                eac1.download_button("📄 下載列印報表 (HTML)", html_ann, file_name=f"Report_Annual_{selected_year_annual}.html", mime="text/html")

                # Excel
                sheet_ann = display_df_annual_with_total[cols_exist_annual].copy()
                det_ann = pd.concat(ann_details_list, ignore_index=True) if ann_details_list else pd.DataFrame()
                excel_ann = to_excel({ "年度總表": [{"dataframe": sheet_ann, "title": title_ann}], "詳細收支": [{"dataframe": det_ann, "title": "各宿舍收支明細"}] })
                eac2.download_button("📊 下載 Excel", excel_ann, file_name=f"Report_Annual_{selected_year_annual}.xlsx")

        # ==============================================================================
        # 頁籤 3: 現金流分析 (不攤提)
        # ==============================================================================
        with tab3:
            st.subheader("現金流收支分析 (不攤提)")
            st.info("此模式下，所有費用將依據「實際支付日期」或「帳單截止日」全額計入當月/當年，不進行跨月攤提。")

            mode = st.radio("檢視模式", ["按月檢視", "按年檢視"], horizontal=True)
            today_cf = datetime.now()
            
            if mode == "按月檢視":
                cf_c1, cf_c2 = st.columns(2)
                cf_year = cf_c1.selectbox("年份", range(today_cf.year-2, today_cf.year+2), index=2, key="cf_m_y")
                cf_month = cf_c2.selectbox("月份", range(1, 13), index=today_cf.month-1, key="cf_m_m")
                cf_period = f"{cf_year}-{cf_month:02d}"
                @st.cache_data
                def get_cf_summary(emps, period, only_mc): return employer_dashboard_model.get_employer_cash_flow_summary(emps, period, only_mc)
                cf_df = get_cf_summary(selected_employers, cf_period, only_my_company)
            else:
                cf_year = st.selectbox("年份", range(today_cf.year-2, today_cf.year+2), index=2, key="cf_y_y")
                cf_period = str(cf_year)
                @st.cache_data
                def get_cf_summary_annual(emps, year, only_mc): return employer_dashboard_model.get_employer_cash_flow_summary_annual(emps, year, only_mc)
                cf_df = get_cf_summary_annual(selected_employers, cf_year, only_my_company)

            if cf_df.empty:
                st.warning(f"在 {cf_period} 期間，找不到相關的現金流紀錄。")
            else:
                cf_df['總收入'] = cf_df['收入(員工月費)'] + cf_df['分攤其他收入']
                total_inc = cf_df['總收入'].sum()
                total_exp = cf_df['我司分攤合約費'].sum() + cf_df['我司分攤雜費'].sum() + cf_df['我司分攤攤銷'].sum()
                net_pl = total_inc - total_exp
                
                total_headcount_cf = 0
                # 處理人數
                if mode == "按月檢視":
                    report_df_cf = employer_dashboard_model.get_employer_resident_details(selected_employers, cf_period, only_my_company)
                    if not report_df_cf.empty:
                        dorm_counts = report_df_cf.groupby('宿舍地址').size().reset_index(name='在住人數')
                        cf_df = pd.merge(cf_df, dorm_counts, on='宿舍地址', how='left')
                        cf_df['在住人數'] = cf_df['在住人數'].fillna(0).astype(int)
                        total_headcount_cf = cf_df['在住人數'].sum()
                    else: cf_df['在住人數'] = 0
                else:
                    # 年檢視：使用後端回傳欄位
                    if '在住人數(年)' in cf_df.columns:
                         total_headcount_cf = cf_df['在住人數(年)'].sum()
                    else:
                         cf_df['在住人數(年)'] = 0

                cf_k1, cf_k2, cf_k3 = st.columns(3)
                cf_k1.metric("現金流總收入", f"NT$ {total_inc:,.0f}")
                cf_k2.metric("現金流總支出", f"NT$ {total_exp:,.0f}")
                cf_k3.metric("現金流淨利", f"NT$ {net_pl:,.0f}", delta=f"{net_pl:,.0f}")

                cf_df['淨損益'] = cf_df['總收入'] - (cf_df['我司分攤合約費'] + cf_df['我司分攤雜費'] + cf_df['我司分攤攤銷'])
                
                # 總計
                cols_sum_cf = ["淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                if mode == "按月檢視": cols_sum_cf.insert(0, "在住人數")
                else: 
                    cols_sum_cf.insert(0, "在住人數(年)")
                    if "目前人數" in cf_df.columns: cols_sum_cf.insert(1, "目前人數")

                # 確保欄位存在才加總
                existing_sum_cols = [c for c in cols_sum_cf if c in cf_df.columns]
                sum_row_cf = cf_df[existing_sum_cols].sum()
                
                sum_row_cf['宿舍地址'] = '總計'
                for c in cf_df.columns:
                    if c not in sum_row_cf: sum_row_cf[c] = ""
                cf_df_final = pd.concat([cf_df, pd.DataFrame([sum_row_cf])], ignore_index=True)

                # 顯示欄位
                cols_show_cf = ["宿舍地址", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                if mode == "按月檢視": cols_show_cf.insert(1, "在住人數")
                else: 
                    cols_show_cf.insert(1, "在住人數(年)")
                    cols_show_cf.insert(2, "目前人數")
                
                cols_exist_cf = [c for c in cols_show_cf if c in cf_df_final.columns]
                
                # 改名
                cf_df_final = cf_df_final.rename(columns={"我司分攤攤銷": "我司分攤支出(不攤提)"})
                cols_exist_cf = [c if c != "我司分攤攤銷" else "我司分攤支出(不攤提)" for c in cols_exist_cf]

                st.dataframe(
                    cf_df_final[cols_exist_cf], width='stretch', hide_index=True,
                    column_config={c: st.column_config.NumberColumn(format="NT$ %d") for c in cols_exist_cf if c not in ["宿舍地址", "在住人數", "在住人數(年)", "目前人數"]}
                )
                
                # 匯出
                st.markdown("---"); st.write("🖨️ **報表輸出**")
                exp_c1, exp_c2 = st.columns(2)
                emp_str = "_".join(selected_employers)[:10]; title_cf = f"{emp_str} 現金流 ({cf_period})"
                
                cf_details_dict = {}; cf_details_list = []
                with st.spinner("準備詳細資料中..."):
                    for _, row in cf_df.iterrows():
                        d_addr = row['宿舍地址']; d_id = dorm_id_map.get(d_addr)
                        if d_id:
                            inc, exp = employer_dashboard_model.get_employer_cash_flow_details_for_dorm(selected_employers, d_id, cf_period)
                            cf_details_dict[d_addr] = (inc, exp)
                            if not inc.empty:
                                inc['宿舍'] = d_addr; inc['類別'] = '收入'; inc = inc.rename(columns={'項目': '細項', '金額': '金額'})
                                cf_details_list.append(inc[['宿舍', '類別', '細項', '金額']])
                            if not exp.empty:
                                exp['宿舍'] = d_addr; exp['類別'] = '支出'; exp = exp.rename(columns={'費用項目': '細項', '分攤後金額': '金額'})
                                cf_details_list.append(exp[['宿舍', '類別', '細項', '金額']])

                kpi_cf = { "headcount": total_headcount_cf, "income": int(total_inc), "expense": int(total_exp), "profit": int(net_pl) }
                html_cf = generate_html_report(title_cf, kpi_cf, cf_df_final, None, cf_details_dict, cols_exist_cf)
                exp_c1.download_button("📄 下載列印報表 (HTML)", html_cf, file_name=f"CashFlow_{cf_period}.html", mime="text/html")

                sheet_cf = cf_df_final[cols_exist_cf].copy()
                det_cf = pd.concat(cf_details_list, ignore_index=True) if cf_details_list else pd.DataFrame()
                excel_cf = to_excel({ "現金流總表": [{"dataframe": sheet_cf, "title": title_cf}], "詳細收支": [{"dataframe": det_cf, "title": "各宿舍收支明細"}] })
                exp_c2.download_button("📊 下載 Excel", excel_cf, file_name=f"CashFlow_{cf_period}.xlsx")