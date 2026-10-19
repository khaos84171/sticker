# sticker — 釘選剪貼簿

永遠顯示在最上層的小視窗，**只保存你自己貼進來的文字**，一鍵複製出來。

- 不會監看系統剪貼簿：你在別處複製的東西不會自己跑進來。
- 內容只在你按「儲存」（或 Ctrl+Enter）、「貼上並儲存」時才加入。
- 卡片只顯示前幾行摘要，按「複製」（或直接點文字）複製的是**完整內容**。
- 關掉再開還在；視窗位置、大小、「釘選」狀態也會記住。
- 自己畫的深色標題列，附「釘選」、「縮小」、「✕ 關閉」鈕。

## 執行

需要 Python 3.9 以上，而且要有 tkinter（Windows 的 python.org 安裝檔已內含；Debian／Ubuntu 要 `sudo apt install python3-tk`）。沒有其他套件要裝。

- Windows：雙擊 `pinclip.pyw`（不會跳出黑色視窗）。
- 其他：`python pinclip.py`

## 用法

| 想做的事 | 做法 |
|---|---|
| 存一段文字 | 在上方輸入框貼上（Ctrl+V），按「儲存」或 Ctrl+Enter |
| 直接把剪貼簿的文字存起來 | 按「貼上並儲存」（只在你按的當下讀一次剪貼簿） |
| 複製 | 按該筆的「複製」，或直接點它的文字 |
| 刪除 | 按該筆的 ✕。下方會出現「已刪除　按這裡復原」，6 秒內可以救回來 |
| 取消／恢復置頂 | 標題列的「已釘選／未釘選」 |
| 縮小 | 標題列的 `—`，視窗收成只剩標題列（仍釘在最上層）；按 `□` 或在標題列連按兩下還原 |
| 關閉 | 標題列右上角 ✕ |
| 移動視窗 | 拖曳標題列 |
| 調整大小 | 拖曳右下角的斜線 |

同樣的文字再存一次，是把舊的那筆移到最前面，不會重複。

## 外框

Windows 上預設用自己畫的標題列（沒有系統外框，所以「縮小」是收成一條標題列，不是縮到工作列；程式會設法讓視窗出現在工作列，被別的視窗蓋住時可以從那裡叫回來）。
macOS／Linux 的無外框視窗常常拿不到鍵盤焦點、打不了字，所以那邊預設用系統外框。
想強制指定，設定環境變數 `PINCLIP_FRAME=custom`（自繪）或 `PINCLIP_FRAME=native`（系統外框）。
自繪標題列在你的電腦上有問題時，用 `native` 就能退回系統外框。

## 資料放哪裡

存成一個 JSON 檔，放在使用者資料夾，不在程式資料夾裡（所以不會被 git 收進去）：

- Windows：`%APPDATA%\pinclip\pinclip.json`
- macOS：`~/Library/Application Support/pinclip/pinclip.json`
- Linux：`~/.local/share/pinclip/pinclip.json`

想換位置，設定環境變數 `PINCLIP_DATA` 為檔案路徑。檔案壞掉時，程式會先留一份 `.bad` 再重新開始，不會直接蓋掉。
程式出錯時會把詳細內容寫到同一個資料夾的 `pinclip_error.log`。

## 測試

```
pip install pytest
python -m pytest
```

介面測試需要顯示器，沒有的話自動跳過；Linux 沒有螢幕時用 `xvfb-run -a python -m pytest`。
