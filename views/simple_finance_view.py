# views/simple_finance_view.py
import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import simple_finance_model

def render():
    st.title("📈 簡易財務分析 (長官試算版)")
    st.info("此報表隱藏了各項繁瑣支出明細。費用以「合約月租金」為基礎進行快速試算：\n\n"
            "1. **房租由我司出**：每月費用 = `房租 × 1.2`\n"
            "2. **房租非我司出，但我司付變動攤銷**：每月費用 = `房租 × 0.2`\n"
            "3. **兩者皆非我司出**：每月費用 = `不計入 (0)`")

    today = datetime.now()
    selected_year = st.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="simple_finance_year")

    @st.cache_data
    def get_data(year):
        return simple_finance_model.get_simplified_annual_finance_data(year)
    
    if st.button("🔍 產生簡易試算報表", key="btn_simple_finance"):
        get_data.clear()
        
    df = get_data(selected_year)
    
    if df is None or df.empty:
        st.warning(f"找不到 {selected_year} 年的數據。")
        return

    # 計算整體大總和
    total_income = df["實際總收入"].sum()
    total_expense = df["試算年支出"].sum()
    total_profit = df["試算淨損益"].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric(f"{selected_year}年 總收入", f"NT$ {total_income:,}")
    col2.metric(f"{selected_year}年 試算總支出", f"NT$ {total_expense:,}")
    col3.metric(f"{selected_year}年 試算淨損益", f"NT$ {total_profit:,}", delta=f"{total_profit:,}")

    st.markdown("##### 各宿舍簡易損益試算詳情")
    
    # 根據淨損益上色
    def style_profit(val):
        if pd.isna(val): return ''
        color = 'red' if val < 0 else 'green' if val > 0 else 'grey'
        return f'color: {color}'

    st.dataframe(
        df.style.apply(lambda x: x.map(lambda y: style_profit(y) if x.name == '試算淨損益' else None)),
        width="stretch",
        hide_index=True,
        column_config={
            "宿舍地址": st.column_config.TextColumn("宿舍地址", width="medium"),
            "雇主": st.column_config.TextColumn("雇主", width="medium"),
            "實際總收入": st.column_config.NumberColumn("實際總收入 (含代收付)", format="NT$ %d"),
            "月租金基準": st.column_config.NumberColumn("合約月租金基準", format="NT$ %d"),
            "試算月費用": st.column_config.NumberColumn("預估每月支出", format="NT$ %d", help="依試算規則推算的月支出"),
            "試算年支出": st.column_config.NumberColumn("預估年度總支出", format="NT$ %d", help="預估每月支出 × 12"),
            "試算淨損益": st.column_config.NumberColumn("試算淨損益", format="NT$ %d"),
            "宿舍備註": st.column_config.TextColumn("宿舍備註")
        }
    )