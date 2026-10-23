# 交付驗證紀錄

驗證日期：2026-10-23。平台：Linux、Python 3.12、Chromium。

## 已執行

| 檢查 | 結果 |
|---|---|
| 全新 `.venv` 安裝固定依賴、`pip check` | 通過 |
| `python tools/launch.py --check` | 通過，建立安裝指紋並可重用環境 |
| `.venv/bin/python -m unittest discover -s tests -v` | 84 項通過，含新手配方、學習／驗證、CSV 與既有核心 |
| `CHROMIUM_PATH=/usr/bin/chromium python tests/learning_browser_smoke.py` | 通過，完整新手研究流程與手機版 |
| `CHROMIUM_PATH=/usr/bin/chromium python tests/browser_smoke.py` | 通過 |
| `CHROMIUM_PATH=/usr/bin/chromium python tests/standalone_smoke.py` | 通過，保留舊版單檔功能 |
| `CHROMIUM_PATH=/usr/bin/chromium python tests/entry_smoke.py` | 通過，隔離預覽及解碼錯誤恢復 |
| `python tests/check_browser_engine.py` | 180 組舊版 Python／JS 逐項一致，涵蓋 1／5／15 分 K；另比對重複／空白欄名解析與選欄 |
| 完整 ZIP 解壓縮後的核心測試與八套 CSV／策略預期值 | 通過 |
| 正式啟動命令與健康、頁面、CSS、編輯器／重播 JS | HTTP 200，FastAPI、8 套範例、66 種積木 |

瀏覽器測試操作真實 Big5 CSV 匯入與回測、積木拖曳／參數、版本變更、複製／刪除策略、口數、扣成本曲線與交易明細匯出、交易跳轉、逐根播放、歷史結果及手機寬度。每套行情的預期價格、費稅與淨損益可在 `examples/acceptance/expected.json` 與測試中核對。

V1.1 新手流程測試另核對四個配方各自的人工進場時間、144 種配方／出場／週期／方向的圖形驗證、交易日 70/30 切分、比較不計算保留期、選定策略與日期不可臨時替換、保留期價格不能影響學習期績效、重複驗證紀錄、樣本偏少與無交易說明、成本壓力的獨立版本，以及重開後的研究保存。

效能觀察：在此 Linux 環境使用 60 個交易日、18,000 根人工分鐘 K，三組學習期比較約 2.44 秒，選定後的保留期與滑價壓力測試約 1.47 秒，相同研究重開讀取約 0.045 秒。這不是跨設備效能保證，也不是市場績效驗證。

時間正確性測試涵蓋：開盤區間完成時間、右側波段確認、多週期完成時間、序列嚴格先後、附加未來行情不改寫既有訊號與區域、移動停損下一分鐘生效、事件不可重複交易、同棒停損優先及跳空、重播不提前揭露盤中平倉或原始平倉價。

## 實際限制

- Windows 啟動腳本與 Windows/Linux CI 已提供，**尚未在實體 Windows 電腦執行驗收**。
- 驗證行情是人工資料；不代表策略具備獲利能力。未使用假的績效數值取代回測。
- 1 分 K 無法還原逐筆先後。碰價順序不明時採保守規則並保留標記；不宣稱精確秒級成交。
- 全版使用 Python／FastAPI／SQLite；附帶的免安裝 HTML 僅涵蓋舊四套策略。
- 原始碼與下載 ZIP 已上傳 GitHub 的 `codex/backtester-download-v1` 分支。雲端設定仍為草稿，尚需環境設定中的儲存與發布步驟；未驗證新雲端工作階段自動還原。
