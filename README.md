# Golden Cross Stock Screener

篩選同時符合三個技術面條件的美股（US equities）：

1. **黃金交叉**：50 日均線（SMA50）近期站上 200 日均線（SMA200）
2. **價漲量增**：股價上漲，且成交量明顯放大（高於近期均量）
3. **MACD 轉正**：MACD 柱狀圖（histogram）由負轉正，或 MACD 線由負轉正

## 為什麼沒有直接附上 5 檔股票？

這支腳本是在一個**沒有對外網路存取權限**的沙盒環境中開發、測試的（Yahoo
Finance / yfinance / Finviz 等資料來源的連線都被環境的 egress proxy 擋掉，
`curl` 回傳 `403`）。因此這裡**無法**實際抓取即時行情、算出「現在」真的符合
條件的股票，只能把篩選邏輯寫成可重複執行的工具。

請在有網路存取權限的環境（自己的電腦、CI、或開啟網路的 Claude Code session）
執行本腳本，取得當下真實的結果——**不要相信任何人（包含 AI）沒有實際跑資料
就報出來的「今天符合黃金交叉的 5 檔股票」，那極可能是編造的。**

## 安裝

```bash
pip install -r requirements.txt
```

## 使用方式

```bash
# 預設：以 S&P 500 成分股為篩選範圍，取前 5 名
python golden_cross_screener.py

# 自訂股票清單（每行一個 ticker）
python golden_cross_screener.py --tickers-file my_tickers.txt

# 調整參數
python golden_cross_screener.py \
    --top 5 \
    --cross-lookback 10 \        # 黃金交叉需發生在最近幾個交易日內
    --macd-lookback 5 \          # MACD 轉正需發生在最近幾個交易日內
    --volume-multiplier 1.5      # 成交量需高於近期均量的倍數
```

## 條件細節

- **黃金交叉**：`SMA50 > SMA200`，且在 `--cross-lookback` 個交易日之前
  `SMA50 <= SMA200`（代表交叉是「最近」發生，不是老早以前就交叉、現在才篩到）。
- **價漲量增**：當日收盤價 > 前一日收盤價，且當日成交量 >
  （近 20 日均量 × `--volume-multiplier`）。
- **MACD 轉正**：MACD histogram（12,26,9 參數）目前 > 0，且在
  `--macd-lookback` 個交易日之前 <= 0。

三個條件同時成立才會被選中；輸出依「相對成交量」（今日量 ÷ 近 20 日均量）
由高到低排序，預設取前 5 檔。

## 輸出欄位

`Ticker / Close / %Chg / Volume / RelVolume / SMA50 / SMA200 / MACD / Signal / Histogram`
