import time
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Kalshi 15m Edge", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 0.8rem; padding-bottom: 0.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.subheader("Kalshi 15m BTC Edge Engine")

col_a, col_b, col_c = st.columns(3)
manual_strike = col_a.number_input("Kalshi Strike (0 = Auto 15m Open)", value=0.0, step=1.0)
pivot_len = col_b.slider("Supply/Demand Pivot Strength", 2, 10, 4)
refresh_sec = col_c.selectbox("Refresh Speed (sec)", [2, 5, 10], index=0)

@st.cache_data(ttl=1)
def get_live_data():
    url = "https://coinbase.com"
    r = requests.get(url, timeout=5)
    data = r.json()
    df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert("America/New_York")
    df = df.sort_values("time").tail(60).reset_index(drop=True)

    kr = requests.get("https://kraken.com", timeout=5).json()
    kraken_price = float(kr["result"]["XXBTZUSD"]["c"][0])
    cb_price = float(df["close"].iloc[-1])
    brti_est = (cb_price + kraken_price) / 2.0
    return df, brti_est

try:
    df, live_price = get_live_data()

    now = df["time"].iloc[-1]
    block_min = now.minute % 15
    mins_left = 15 - block_min
    window_start = now - pd.Timedelta(minutes=block_min)
    window_df = df[df["time"] >= window_start]
    auto_strike = float(window_df["open"].iloc[0]) if not window_df.empty else float(df["open"].iloc[-1])
    strike = manual_strike if manual_strike > 0 else auto_strike
    diff = live_price - strike

    c_range = (df["high"] - df["low"]).replace(0, 0.01)
    buy_pct = (df["close"] - df["low"]) / c_range
    df["bar_delta"] = df["volume"] * (buy_pct - (1.0 - buy_pct))
    avg_vol = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = df["volume"].iloc[-1] / avg_vol if avg_vol > 0 else 1.0
    cur_buy_pct = float(buy_pct.iloc[-1] * 100.0)
    net_delta_15m = float(window_df["bar_delta"].sum()) if not window_df.empty else 0.0

    supply_levels = []
    demand_levels = []
    for i in range(pivot_len, len(df) - pivot_len):
        if df["high"].iloc[i] == df["high"].iloc[i - pivot_len : i + pivot_len + 1].max():
            supply_levels.append(float(df["high"].iloc[i]))
        if df["low"].iloc[i] == df["low"].iloc[i - pivot_len : i + pivot_len + 1].min():
            demand_levels.append(float(df["low"].iloc[i]))

    nearest_supply = min([s for s in supply_levels if s >= live_price], default=max(supply_levels) if supply_levels else live_price + 50)
    nearest_demand = max([d for d in demand_levels if d <= live_price], default=min(demand_levels) if demand_levels else live_price - 50)

    recent = df.tail(14)
    mid = len(recent) // 2
    low1 = recent["low"].iloc[:mid].min()
    low2 = recent["low"].iloc[mid:].min()
    high1 = recent["high"].iloc[:mid].max()
    high2 = recent["high"].iloc[mid:].max()

    if low2 > low1 and live_price > recent["close"].iloc[-2]:
        pattern = "FORMING W (HIGHER LOW)"
        up_prob = min(92, int(62 + (cur_buy_pct - 50) * 0.4 + (10 if diff > 0 else 0)))
    elif high2 < high1 and live_price < recent["close"].iloc[-2]:
        pattern = "FORMING M (LOWER HIGH)"
        up_prob = max(8, int(38 - (50 - cur_buy_pct) * 0.4 - (10 if diff < 0 else 0)))
    else:
        pattern = "SCANNING STRUCTURE"
        up_prob = int(np.clip(50 + (diff / 2.0) + (cur_buy_pct - 50) * 0.25, 10, 90))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("BRTI Live Price", f"${live_price:,.2f}", f"{diff:+.2f} vs Strike")
    m2.metric("15m Strike Target", f"${strike:,.2f}", f"{mins_left}m left")
    m3.metric("UP (YES) Prob", f"{up_prob}%", pattern)
    m4.metric("Order Flow Buy %", f"{cur_buy_pct:.0f}% BUY", f"{vol_ratio:.1f}x Vol | {net_delta_15m:+.1f} Delta")

    fig = go.Figure(data=[
        go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            increasing_line_color="#00ff88", decreasing_line_color="#ff4466", name="BTC"
        )
    ])

    fig.add_hline(y=strike, line_dash="dash", line_color="yellow", annotation_text=f"STRIKE ${strike:,.2f}")
    fig.add_hrect(y0=nearest_supply - 8, y1=nearest_supply + 8, fillcolor="purple", opacity=0.25, line_width=0, annotation_text="SUPPLY")
    fig.add_hrect(y0=nearest_demand - 8, y1=nearest_demand + 8, fillcolor="aqua", opacity=0.25, line_width=0, annotation_text="DEMAND")

    fig.update_layout(
        template="plotly_dark",
        height=400,
        margin=dict(l=10, r=10, t=20, b=20),
        xaxis_rangeslider_visible=False
    )
    st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"Feed syncing: {e}")

time.sleep(refresh_sec)
st.rerun()
