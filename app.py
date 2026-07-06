import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import math
import requests
from io import BytesIO

st.set_page_config(page_title="全銘柄スクリーニングツール", page_icon="📈", layout="wide")
st.title("📈 全銘柄スクリーニングツール")
st.caption("JPX全上場銘柄対応 ＋ RSI ＋ GC予兆 ＋ カップ＆ハンドル検知")

with st.expander("📖 見方を見る（クリックで開く）"):
    st.markdown("""
| 項目 | 意味 | 目安 |
|---|---|---|
| **RSI** | 売られすぎ・買われすぎを示す指標（0〜100） | 30以下が買いサイン候補 |
| **GC予兆** | 短期移動平均線が長期線に近づいている状態 | 「約◯日後」が小さいほど近い |
| **乖離率(%)** | 短期線と長期線の差（マイナス=短期線が下） | 0に近いほどGCが近い |
| **縮小スピード** | 乖離率が縮まる速さ | 大きいほど勢いよく接近中 |
| **C&H予兆** | カップ＆ハンドル形成中の可能性 | ◎が最有力候補 |
| **出来高** | その日に取引された株数 | 多いほど注目されている |

**💡 組み合わせのポイント**
- RSI30以下 ＋ GC予兆あり → 売られすぎから反転の可能性
- C&H予兆◎ ＋ GC予兆あり → ブレイクアウト直前の有力候補
- 乖離率が小さい ＋ 縮小スピードが大きい → GCが近い有力候補
    """)

@st.cache_data(ttl=60*60*24)
def load_jpx_tickers():
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    try:
        res = requests.get(url, timeout=15)
        df = pd.read_excel(BytesIO(res.content), header=0)
        df.columns = df.columns.str.strip()
        code_col = [c for c in df.columns if "コード" in str(c)][0]
        name_col = [c for c in df.columns if "銘柄名" in str(c)][0]
        market_col = [c for c in df.columns if "市場・商品区分" in str(c) or "市場" in str(c)][0]
        df = df[[code_col, name_col, market_col, "17業種区分"]].dropna()
        df[code_col] = df[code_col].astype(str).str.zfill(4) + ".T"
        df.columns = ["コード", "銘柄名", "市場", "業種"]
        return df
    except Exception as e:
        st.error(f"JPX銘柄リスト取得エラー: {e}")
        return None

def safe_float(val):
    try:
        f = float(val)
        if math.isnan(f):
            return None
        return f
    except:
        return None

def detect_gc_sign(hist, short_window=25, long_window=75):
    if len(hist) < long_window + 5:
        return None, None, None
    hist = hist.copy()
    hist["SMA_short"] = hist["Close"].rolling(short_window).mean()
    hist["SMA_long"] = hist["Close"].rolling(long_window).mean()
    hist["gap_pct"] = (hist["SMA_short"] - hist["SMA_long"]) / hist["SMA_long"] * 100
    hist = hist.dropna(subset=["SMA_short", "SMA_long", "gap_pct"])
    if len(hist) < 5:
        return None, None, None
    current_gap = safe_float(hist["gap_pct"].iloc[-1])
    if current_gap is None:
        return None, None, None
    recent = hist["gap_pct"].tail(5)
    slope = safe_float(recent.iloc[-1] - recent.iloc[0])
    if slope is None:
        return None, None, None
    if current_gap < 0 and slope > 0:
        days_to_cross = abs(current_gap) / (slope / 5) if slope != 0 else None
        est = round(days_to_cross, 1) if days_to_cross and days_to_cross < 60 else None
        return round(current_gap, 2), round(slope, 3), est
    else:
        return None, None, None

def detect_cup_and_handle(hist):
    if len(hist) < 60:
        return "-"
    try:
        close = hist["Close"].values
        n = len(close)
        cup_period = close[-120:] if n >= 120 else close
        cup_len = len(cup_period)
        left_high = max(cup_period[:cup_len//3])
        bottom = min(cup_period[cup_len//3: 2*cup_len//3])
        right_high = max(cup_period[2*cup_len//3:])
        cup_depth = (left_high - bottom) / left_high * 100
        if not (15 <= cup_depth <= 60):
            return "-"
        recovery = right_high / left_high
        if recovery < 0.85:
            return "-"
        handle_period = close[-20:]
        handle_high = max(handle_period)
        handle_low = min(handle_period)
        handle_depth = (handle_high - handle_low) / handle_high * 100
        if not (3 <= handle_depth <= 25):
            return "-"
        near_breakout = close[-1] >= handle_high * 0.97
        vol = hist["Volume"].values[-20:]
        vol_trend = vol[-5:].mean() < vol[:10].mean()
        if near_breakout and vol_trend:
            return "◎"
        elif recovery >= 0.90 and handle_depth <= 15:
            return "○"
        elif recovery >= 0.85:
            return "△"
        else:
            return "-"
    except:
        return "-"

st.sidebar.header("⚙️ スクリーニング条件")
rsi_max = st.sidebar.slider("RSI上限（以下を抽出）", 10, 70, 30)

st.sidebar.header("💴 株価帯フィルター")
price_min = st.sidebar.number_input("最低株価（円）", value=0, step=100)
price_max = st.sidebar.number_input("最高株価（円）", value=100000, step=1000)

st.sidebar.header("🔔 GC予兆フィルター")
gc_days_max = st.sidebar.slider("GC予測まで何営業日以内？", 5, 30, 15)
gc_only = st.sidebar.checkbox("GC予兆銘柄のみ表示", value=False)

st.sidebar.header("🏆 C&Hフィルター")
ch_only = st.sidebar.checkbox("C&H予兆銘柄のみ表示", value=False)

st.sidebar.header("📋 銘柄選択")

jpx_df = load_jpx_tickers()

if jpx_df is not None:
    st.sidebar.success(f"✅ JPXより{len(jpx_df)}銘柄取得済み")

    st.sidebar.markdown("**🔎 銘柄名で検索**")
    search_word = st.sidebar.text_input("銘柄名またはコードで検索", placeholder="例：JX金属、トヨタ、6758")
    if search_word:
        matched = jpx_df[
            jpx_df["銘柄名"].str.contains(search_word, na=False) |
            jpx_df["コード"].str.contains(search_word, na=False)
        ]
        if not matched.empty:
            for _, row in matched.head(10).iterrows():
                label = f"{row['コード']} {row['銘柄名']}"
                if st.sidebar.button(label, key=f"search_{row['コード']}"):
                    current = st.session_state.get("tickers_input", "")
                    tickers_set = set(current.strip().split("\n")) if current.strip() else set()
                    tickers_set.add(row["コード"])
                    st.session_state["tickers_input"] = "\n".join(sorted(tickers_set))
                    st.rerun()
        else:
            st.sidebar.warning("該当する銘柄が見つかりませんでした")

    markets = ["すべて"] + sorted(jpx_df["市場"].unique().tolist())
    selected_market = st.sidebar.selectbox("市場で絞り込み", markets)
    if st.sidebar.button("📊 選択した市場の銘柄をセット"):
        if selected_market == "すべて":
            tickers_list = jpx_df["コード"].tolist()
        else:
            tickers_list = jpx_df[jpx_df["市場"] == selected_market]["コード"].tolist()
        st.session_state["tickers_input"] = "\n".join(tickers_list)
        st.rerun()

    st.sidebar.markdown("**🏭 業種別プリセット**")
    sectors = sorted(jpx_df["業種"].unique().tolist())
    selected_sector = st.sidebar.selectbox("業種を選択", ["選択してください"] + sectors)
    if st.sidebar.button("🏭 選択した業種の銘柄をセット"):
        if selected_sector != "選択してください":
            tickers_list = jpx_df[jpx_df["業種"] == selected_sector]["コード"].tolist()
            st.session_state["tickers_input"] = "\n".join(tickers_list)
            st.sidebar.success(f"{len(tickers_list)}銘柄をセットしました！")
            st.rerun()

else:
    st.sidebar.error("JPX銘柄リストの取得に失敗しました")

default_tickers = "7203.T\n6758.T\n9984.T\n6861.T\n8306.T\n7974.T\n6902.T\n9432.T"
tickers_input = st.sidebar.text_area(
    "銘柄コードを1行ずつ入力（.T = 東証）",
    value=st.session_state.get("tickers_input", default_tickers),
    height=150,
    key="tickers_input"
)

ticker_count = len([t for t in tickers_input.strip().split("\n") if t.strip()])
if ticker_count > 500:
    st.sidebar.warning(f"⚠️ {ticker_count}銘柄は時間がかかります。株価帯フィルターで絞り込みを推奨します。")

if st.button("🔍 スクリーニング実行", type="primary"):
    tickers = [t.strip() for t in tickers_input.strip().split("\n") if t.strip()]
    results = []
    progress = st.progress(0)
    status = st.empty()

    for i, ticker in enumerate(tickers):
        status.text(f"取得中: {ticker} ({i+1}/{len(tickers)})")
        progress.progress((i + 1) / len(tickers))
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if hist.empty or len(hist) < 15:
                continue
            hist = hist.dropna(subset=["Close", "Volume"])
            if len(hist) < 15:
                continue
            close_val = safe_float(hist["Close"].iloc[-1])
            if close_val is None:
                continue
            if close_val < price_min or close_val > price_max:
                continue
            hist["RSI"] = ta.momentum.RSIIndicator(hist["Close"], window=14).rsi()
            rsi_val = safe_float(hist["RSI"].iloc[-1])
            volume_val = safe_float(hist["Volume"].iloc[-1])
            if rsi_val is None:
                continue
            gap_pct, slope, est_days = detect_gc_sign(hist)
            if gap_pct is not None:
                gc_label = f"⚡ 約{est_days}日後" if est_days else "📈 接近中"
            else:
                gc_label = "-"
            ch_label = detect_cup_and_handle(hist)

            jp_name = None
            if jpx_df is not None:
                row = jpx_df[jpx_df["コード"] == ticker]
                if not row.empty:
                    jp_name = row.iloc[0]["銘柄名"]
            if not jp_name:
                info = stock.info
                jp_name = info.get("longName") or info.get("shortName") or ticker

            results.append({
                "銘柄コード": ticker,
                "銘柄名": jp_name,
                "株価(円)": round(close_val),
                "RSI": round(rsi_val, 1),
                "GC予兆": gc_label,
                "C&H予兆": ch_label,
                "乖離率(%)": str(round(gap_pct, 2)) if gap_pct is not None else "-",
                "縮小スピード": str(round(slope, 3)) if slope is not None else "-",
                "推定GC日数": est_days if est_days else 999,
                "出来高": int(volume_val) if volume_val else 0,
            })
        except Exception:
            continue

    status.empty()
    progress.empty()

    if not results:
        st.warning("データを取得できませんでした。")
    else:
        df = pd.DataFrame(results)
        if gc_only:
            df = df[df["GC予兆"] != "-"]
        if ch_only:
            df = df[df["C&H予兆"] != "-"]

        display_cols = ["銘柄コード", "銘柄名", "株価(円)", "RSI", "GC予兆", "C&H予兆", "乖離率(%)", "縮小スピード", "出来高"]

        st.subheader(f"📊 全銘柄一覧（{len(df)}銘柄）")
        st.dataframe(df[display_cols], use_container_width=True)

        st.subheader(f"🎯 RSI {rsi_max}以下の銘柄")
        hit = df[df["RSI"] <= rsi_max]
        if hit.empty:
            st.info("条件に一致する銘柄はありませんでした。")
        else:
            st.success(f"{len(hit)}銘柄が条件に一致しました！")
            st.dataframe(hit[display_cols], use_container_width=True)

        st.subheader(f"⚡ GC予兆銘柄（{gc_days_max}営業日以内）")
        gc_hit = df[(df["GC予兆"] != "-") & (df["推定GC日数"] <= gc_days_max)]
        if gc_hit.empty:
            st.info("条件に一致するGC予兆銘柄はありませんでした。")
        else:
            st.success(f"{len(gc_hit)}銘柄にGC予兆あり！")
            st.dataframe(gc_hit[display_cols], use_container_width=True)

        st.subheader("🏆 カップ＆ハンドル予兆銘柄")
        ch_hit = df[df["C&H予兆"].isin(["◎", "○"])]
        if ch_hit.empty:
            st.info("C&H予兆銘柄はありませんでした。")
        else:
            st.success(f"{len(ch_hit)}銘柄にC&H予兆あり！")
            st.dataframe(ch_hit[display_cols], use_container_width=True)

        st.subheader("🌟 GC予兆 ＋ C&H予兆 両方あり（最有力候補）")
        best = df[(df["GC予兆"] != "-") & (df["C&H予兆"].isin(["◎", "○"])) & (df["推定GC日数"] <= gc_days_max)]
        if best.empty:
            st.info("両方の条件に一致する銘柄はありませんでした。")
        else:
            st.success(f"🎯 {len(best)}銘柄が最有力候補です！")
            st.dataframe(best[display_cols], use_container_width=True)