
# iLearning → iPad Calendar (ICS Subscription)

這個小工具會：
1. 登入你的 iLearning（Moodle 類系統）。  
2. 抓取每門課的「作業清單」頁面（`/mod/assign/index.php?id=<課程ID>`）。  
3. 解析作業名稱與繳交期限，產生 `ilearning.ics`。  
4. 你在 iPad/Apple Calendar 訂閱這個 `.ics`，就能每天自動更新，不怕漏交。

> **注意**：不同學校的 iLearning 佈景或 SSO 登入可能略有差異。此工具的預設選擇器是針對 Moodle 風格的「作業索引表格」。若你的 HTML 不同，請微調 `parse_assign_table()`。

---

## 方案 A（最快）：先檢查 iLearning 有沒有官方 iCal 訂閱

很多 Moodle/校務 LMS 內建「行事曆匯出 / 訂閱（iCal）」：  
**行事曆 → 匯出 → 選擇所有課程/所有事件 → 取得 iCal URL**  
把該 URL 直接在 iPad：**設定 → 行事曆 → 帳號 → 新增「訂閱的行事曆」** 貼上即可。

如果你找得到官方 iCal，就不用此工具。

---

## 方案 B：用本工具自動抓 + 發佈 ICS（推薦）

### 1) Fork/建立一個 GitHub Repo，放入本專案檔
- `ilearning_to_ics.py`
- `requirements.txt`
- `.github/workflows/publish-ics.yml`（下面第 3 步會建立）
- `public/` 資料夾會存放輸出的 `ilearning.ics`

### 2) 在 GitHub Repo → Settings → Secrets and variables → Actions 新增 Secrets
- `ILEARNING_BASE_URL` 例如 `https://ilearning.yourschool.edu`
- `ILEARNING_USERNAME`
- `ILEARNING_PASSWORD`
- `COURSE_IDS` 例：`123,456,789`（對應各課程的 `id=`）
- （選）`TIMEZONE` 例：`Asia/Taipei`

### 3) 啟用 GitHub Pages + Actions
將 workflow 設為每 6 小時跑一次，並把 `public/ilearning.ics` 發佈到 GitHub Pages：

- Repo → Settings → Pages：Source 選 **GitHub Actions**。
- push 後，Pages 會提供一個網址類似 `https://<user>.github.io/<repo>/ilearning.ics`。

### 4) 在 iPad 訂閱
iPad：**設定 → 行事曆 → 帳號 → 新增「訂閱的行事曆」**，
貼上剛才的 `https://.../ilearning.ics`（或把 `https://` 改成 `webcal://`）。  
接著在 **設定 → 行事曆 → 帳號 → 取得新資料** 把「訂閱行事曆」的擷取頻率設為 15 分鐘或每小時。

---

## 本機測試（可選）
1. 建立 `.env`（或用環境變數）並填入：
```
ILEARNING_BASE_URL=https://ilearning.yourschool.edu
ILEARNING_USERNAME=your_id
ILEARNING_PASSWORD=your_pw
COURSE_IDS=123,456
TIMEZONE=Asia/Taipei
```
2. 安裝依賴並執行：
```bash
pip install -r requirements.txt
python ilearning_to_ics.py
```
生成的 `public/ilearning.ics` 可直接用行事曆開啟測試。

---

## 常見問題

**Q1. 我校是 SSO（單一登入），`/login/index.php` 會轉跳到校園入口？**  
A：多數 SSO 仍會到一個表單頁面；你可能需要在 `login()` 補上額外的 POST/redirect 處理。
若 SSO 無法機器登入，建議改採「方案 A 官方 iCal」或「方案 C：iOS 捷徑」。

**Q2. 只抓得到作業（assign），測驗（quiz）也想要？**  
A：照 `parse_assign_table()` 的寫法複製一份 `parse_quiz_table()`，抓 `/mod/quiz/index.php?id=<課程ID>`；
把結果一起丟進 `build_calendar()` 即可。

**Q3. 會不會重複建立事件？**  
A：事件 UID 以「作業連結 + 標題」做雜湊，日曆端會視為同一事件（被覆蓋），避免重複。

**Q4. 時區/提醒**  
A：預設 `Asia/Taipei`，提醒在 **前 1 天** 與 **前 3 小時**。可自行改程式。

---

## 方案 C：不寫伺服器，用 iOS 捷徑每天自動抓（僅當你已登入 iLearning）

1. 在 Safari 先手動登入 iLearning（讓 Cookie 在裝置上）。  
2. 用「捷徑」App 建新捷徑（可命名：*iLearning Deadlines Sync*）：
   - **取得網頁內容**（URL 指向你的「作業清單/最近期限」頁面）  
   - **在網頁上執行 JavaScript**（輸出 JSON）：
     ```javascript
     const rows = [...document.querySelectorAll('a[href*="/mod/assign/"]')];
     const out = rows.map(a => {
       const tr = a.closest('tr');
       const cells = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
       const dueText = cells.reverse().find(t => /繳交|截止|到期|due/i.test(t)) || '';
       return { title: a.innerText.trim(), link: a.href, due: dueText };
     });
     JSON.stringify(out);
     ```
   - **取得字典值**（把 JSON 轉成清單）→ **重複執行每個項目**：  
     - **將文字轉日期**（把 `due` 變日期；必要時先用「取代文字」清掉「繳交期限：」等前綴）  
     - **尋找行事曆事件**（用 `URL 字段` 或 `備註` 包含 `link`，若存在則更新，否則新增）  
     - **新增行事曆事件**：標題加上 `[iLearning]`，提醒設 1 天和 3 小時前，備註放 `link`。
3. **自動化** → **個人** → **時間** 每天 08:00，關閉「執行前先詢問」。

此法全部在 iPad 上完成，但若 iLearning 有動態渲染/需要分頁，就比較不穩。

---

## 安全
- GitHub Actions 用 **Secrets** 保存帳密；ICS 只含標題與時間，不會含你的帳密。
- 若你擔心公開 ICS，被人推測你的課程與作業，可把 Pages 設為私有，或將 ICS 發佈到私有雲端（自架 WebDAV/NAS）。

祝順利不漏交 🎯
