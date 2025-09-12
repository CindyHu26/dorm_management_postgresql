import streamlit as st
import pandas as pd
from data_models import analytics_model, dormitory_model, meter_model

def render():
    """渲染「費用分析」儀表板"""
    st.header("水電費用分析儀表板")
    st.info("此工具用於追蹤單一電水錶的歷史費用，並自動偵測潛在的異常帳單。")
    
    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")
    tab1, tab2 = st.tabs(["🚨 金額異常數據警告", "💧 用量異常數據警告"])

    with tab1:
        st.subheader("🚨 費用異常數據警告")
        
        with st.expander("點此查看異常判斷說明"):
            st.markdown("""
            系統採用統計學中的 **IQR (四分位距)** 方法來自動偵測異常值：
            1.  **分組計算**：將同一個電水錶的所有歷史帳單分為一組。
            2.  **找出中間值**：計算這組數據中，排名在25% (Q1)和75% (Q3)的金額。
            3.  **定義正常範圍**：系統會定義一個合理的「正常費用範圍」。
            4.  **揪出異常**：任何**遠遠超出**這個正常範圍的帳單，就會被標記為「費用過高」或「費用過低」。
            
            *註：至少需要4筆歷史帳單，系統才能進行有效的統計分析。*
            """)

        @st.cache_data
        def get_anomalies():
            return analytics_model.find_expense_anomalies()
            
        anomalies_df = get_anomalies()
        
        if anomalies_df.empty:
            st.success("恭喜！目前系統未偵測到任何費用異常的帳單紀錄。")
        else:
            st.warning(f"系統偵測到 {len(anomalies_df)} 筆費用可能存在異常的帳單，請您關注：")

            def style_anomaly_reason(val):
                if '過高' in str(val):
                    color = 'red'
                elif '過低' in str(val):
                    color = 'green'
                else:
                    color = 'inherit'
                return f'color: {color}; font-weight: bold;'

            # --- 在 column_config 中，將布林值轉換為更容易閱讀的 "是/否" ---
            st.dataframe(
                anomalies_df.style.apply(lambda x: x.map(style_anomaly_reason) if x.name == '判斷' else [''] * len(x)),
                width="stretch", 
                hide_index=True,
                column_config={
                    "異常金額": st.column_config.NumberColumn(format="NT$ %d"),
                    "是否為代收代付": st.column_config.CheckboxColumn(
                        "代收代付?",
                        help="是否為代收代付帳款",
                        default=False,
                    ),
                }
            )

    st.markdown("---")

    with tab2:
        st.subheader("用量波動異常偵測")
        with st.expander("點此查看異常判斷說明"):
            st.markdown("""
            系統會將每一筆帳單的用量，分別與**「上一期帳單」**和**「去年同期的平均用量」**進行比較。
            - 只要波動超過 **±10%**，就會被標記為「用量過高」或「用量過低」。
            - 此功能有助於快速發現季節性用電異常或潛在的漏水問題。
            *註：至少需要2筆歷史帳單才能與前期比較；需要有去年的資料才能與同期比較。*
            """)

        @st.cache_data
        def get_usage_anomalies():
            return analytics_model.find_usage_anomalies()
            
        usage_anomalies_df = get_usage_anomalies()

        if usage_anomalies_df.empty:
            st.success("恭喜！目前系統未偵測到任何用量波動異常的帳單紀錄。")
        else:
            st.warning(f"系統偵測到 {len(usage_anomalies_df)} 筆用量波動異常的帳單，請您關注：")

            def style_usage_anomaly(val):
                if '過高' in str(val): color = 'red'
                elif '過低' in str(val): color = 'green'
                else: color = 'inherit'
                return f'color: {color}; font-weight: bold;'
            
            st.dataframe(
                usage_anomalies_df.style.apply(lambda x: x.map(style_usage_anomaly) if x.name == '判斷' else [''] * len(x)),
                width="stretch", hide_index=True,
                column_config={
                    "本期用量": st.column_config.NumberColumn(format="%.2f"),
                    "比較基準": st.column_config.NumberColumn(format="%.2f"),
                    "代收代付?": st.column_config.CheckboxColumn(default=False),
                }
            )

    st.markdown("---")
    st.subheader("📈 歷史費用趨勢查詢")
    
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供分析。")
        return
    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "步驟一：請選擇要分析的宿舍",
        options=[None] + list(dorm_options.keys()),
        format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x)
    )

    if selected_dorm_id:
        meters = meter_model.get_meters_for_dorm_as_df(selected_dorm_id)
        if meters.empty:
            st.info("此宿舍尚未登錄任何獨立的電水錶。")
        else:
            meter_options = {m['id']: f"{m['類型']} ({m['錶號']}) - {m.get('對應區域/房號', '')}" for _, m in meters.iterrows()}
            selected_meter_id = st.selectbox(
                "步驟二：請選擇要分析的電水錶",
                options=[None] + list(meter_options.keys()),
                format_func=lambda x: "請選擇..." if x is None else meter_options.get(x)
            )

            if selected_meter_id:
                st.markdown(f"#### 分析結果: {meter_options[selected_meter_id]}")
                
                @st.cache_data
                def get_data(meter_id):
                    return analytics_model.get_bill_history_for_meter(meter_id)

                history_df = get_data(selected_meter_id)

                if history_df.empty:
                    st.info("此電水錶目前沒有任何費用帳單紀錄。")
                else:
                    # --- 【核心修改點】---
                    chart_df = history_df.set_index('帳單結束日')

                    st.markdown("##### 金額趨勢圖")
                    st.line_chart(chart_df['帳單金額'])
                    
                    if '用量(度/噸)' in chart_df.columns and chart_df['用量(度/噸)'].notna().any():
                        st.markdown("##### 用量趨勢圖")
                        
                        # --- 【核心修正】在這裡強制將資料轉換為數字格式，增強圖表的穩定性 ---
                        chart_df['用量(度/噸)'] = pd.to_numeric(chart_df['用量(度/噸)'], errors='coerce')
                        
                        st.line_chart(chart_df['用量(度/噸)'])
                    
                    with st.expander("查看原始數據"):
                        st.dataframe(history_df, width="stretch", hide_index=True)