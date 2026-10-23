# 實作與驗證對照

原始任務完整保留於 `DEVELOPMENT_TASK_V1.md`。以下為 Python／FastAPI 完整版；舊單檔 HTML 不涵蓋新增功能。

## 積木目錄

| 代碼 | 名稱 | 執行類型 | 主要實作 |
|---|---|---|---|
| P01 | 開盤區間 | `opening_range` | `blocks.py` |
| P02 | 前 N 根高低點 | `rolling_range` | `blocks.py` |
| P03 | 已確認波段高低點 | `swing` | `blocks.py` |
| P04 | 前日關鍵價 | `previous_day` | `blocks.py` |
| P05 | 當日截至目前高低點 | `day_range` | `blocks.py` |
| P06 | 自動支撐壓力區 | `support_resistance` | `blocks.py` |
| P07 | 盤整箱體 | `box` | `blocks.py` |
| P08 | 開盤缺口 | `gap` | `blocks.py` |
| P09 | 移動平均 | `ma` | `blocks.py` |
| P10 | 事件發生時鎖定價格 | `snapshot` | `blocks.py` |
| E01 | 價格突破 | `breakout` | `blocks.py` |
| E02 | 突破後回踩確認 | `retest` | `blocks.py` |
| E03 | 支撐反彈 | `bounce` | `blocks.py` |
| E04 | 壓力反轉 | `rejection` | `blocks.py` |
| E05 | 假突破反向訊號 | `false_break` | `blocks.py` |
| E06 | N 字順勢回調 | `n_pattern` | `blocks.py` |
| E07 | 結構突破 BOS | `bos` | `blocks.py` |
| E08 | 結構反轉 CHoCH | `choch` | `blocks.py` |
| E09 | 吞噬 K | `engulfing` | `blocks.py` |
| E10 | 影線反轉 K | `pinbar` | `blocks.py` |
| E11 | 連續 K 棒 | `consecutive` | `blocks.py` |
| E12 | 箱體突破 | `box_break` | `blocks.py` |
| F01 | 允許交易時段 | `time_filter` | `blocks.py` |
| F02/F03 | HH/HL 或 LH/LL 趨勢 | `trend_filter` | `blocks.py` |
| F04 | 參考區間大小 | `range_filter` | `blocks.py` |
| F05 | K 棒實體大小 | `body_filter` | `blocks.py` |
| F06 | 距參考價格點數 | `distance_filter` | `blocks.py` |
| F07 | 回調深度比例 | `pullback_filter` | `blocks.py` |
| F08 | 指定第 N 次訊號 | `occurrence_filter` | `blocks.py` |
| F09/L06 | 訊號有效期限 | `expire` | `blocks.py` |
| F10 | 停損後冷卻 | `cooldown_filter` | `blocks.py` |
| F11 | 每日交易次數限制 | `daily_count_filter` | `blocks.py` |
| F12 | 停損最大距離 | `risk_distance_filter` | `blocks.py` |
| F13 | 最近支撐壓力空間 | `space_filter` | `blocks.py` |
| F14 | 星期與日期排除 | `calendar_filter` | `blocks.py` |
| S01 | 固定點數停損 | `stop_fixed` | `matching.py` |
| S02 | 訊號 K 棒停損 | `stop_signal` | `matching.py` |
| S03 | 前一根 K 棒停損 | `stop_previous` | `matching.py` |
| S04 | 波段結構停損 | `stop_structure` | `matching.py` |
| S05 | 支撐壓力停損 | `stop_zone` | `matching.py` |
| S06 | 區間邊界停損 | `stop_range` | `matching.py` |
| S07 | 移動結構停損 | `stop_trailing_structure` | `matching.py` |
| S08 | 追蹤點數停損 | `stop_trailing_points` | `matching.py` |
| X01 | 固定點數停利 | `target_fixed` | `matching.py` |
| X02 | 固定風險報酬比 | `target_rr` | `matching.py` |
| X03 | 最近支撐壓力停利 | `target_reference` | `matching.py` |
| X04 | 結構失效出場 | `exit_structure` | `blocks.py` |
| X05 | 反向反轉 K 出場 | `exit_reversal` | `blocks.py` |
| X06 | 移動平均出場 | `exit_ma` | `blocks.py` |
| X07 | 持倉 N 根出場 | `exit_bars` | `blocks.py` |
| X08 | 指定時間平倉 | `exit_time` | `blocks.py` |
| X09 | 突破失敗出場 | `exit_failure` | `blocks.py` |
| X10 | N 字結構失效 | `exit_n_failure` | `blocks.py` |
| X11 | 獲利回吐百分比 | `exit_giveback` | `blocks.py` |
| X12 | 連續反向 K 出場 | `exit_consecutive` | `blocks.py` |
| L01 | AND 全部成立 | `and` | `blocks.py` |
| L02 | OR 任一成立 | `or` | `blocks.py` |
| L03 | NOT 排除條件 | `not` | `blocks.py` |
| L04 | 依序 A → B → C | `sequence` | `blocks.py` |
| L05 | 指定根數內出現 N 次 | `count` | `blocks.py` |
| L07 | 成立後保持／重置 | `reset` | `blocks.py` |
| L08 | 延後 N 根觸發 | `delay` | `blocks.py` |
| L09 | 條件成立邊緣事件 | `event` | `blocks.py` |
| C01 | 收盤與價格比較 | `compare` | `blocks.py` |
| C02 | K 棒方向確認 | `candle` | `blocks.py` |
| C03 | 參考價觸及與收盤確認 | `touch_reference` | `blocks.py` |

## 驗證範圍

- `test_extended.py`：八套人工行情逐筆驗收、30 分 K、合約界線、所有市場積木可評估、多步事件、每日虧損、FastAPI／策略庫與重播。
- `test_block_details.py`：不同停損與停利基準、移動停損、價格來源、同價波段、獨立區域測試、突破確認／次數／實體、CHoCH、吞噬與影線、事件不可重用。
- `test_backtester.py`：原有 CSV、訊號、成本、跳空、同棒碰價、不跨日、不反手及 SQLite 重現測試。
- `browser_smoke.py`：真正拖曳與編輯、參數驗證、自動版本、複製／刪除、八套 CSV 實際回測、報表、圖表跳轉／播放、匯出及手機排版。

## 明確採用的語意

- E01「觸價」含剛好碰價；「穿越」需超過。所有這類行情條件仍在該根完成才確認；實際觸價委託另由確認後的 1 分資料模擬。
- E02 鎖定突破時價格；離開後再進入才計新回踩。指定次數回踩後可等同區域內紅／黑 K；突破確認 K 則須後續 K 完成。
- P06 第一個已確認且反應足夠的波段測試計一次；之後只以離開、返回、後續反應計新測試，不將同一回踩的波段確認重複計次。
- N 字回調與序列事件在失效／逾期後取消；序列期限從 A 開始算，B/C 均須嚴格較晚。
- S02/S03 使用進場訊號所屬週期的已完成 K，不使用下一根進場 K 尚未知的高低價。
- 不同保護價同時生效，採最緊停損與最近停利；跳空後保護價不合法則取消進場。
- 風險報酬報表使用扣成本後損益除以初始風險金額；移動停損不改寫初始風險。
- 一般多重出場採任一成立；同開盤碰保護停損時停損優先於已排定的一般平倉。
- 重播顯示價格候選位置時，只能在其右側確認時間到達後顯示；盤中成交要等該分鐘完成才能得知。

## 平台驗證限制

- 目前完成 Linux／Chromium 驗證，Windows 矩陣已配置，實體 Windows 操作尚未執行。
- 無逐筆價格路徑、保證成交、委託簿及交易所特殊行事曆；相應的不確定與資料缺漏都保留於結果。
- 首次安裝需套件網路；正常歷史回測不需即時行情或第三方金鑰。
