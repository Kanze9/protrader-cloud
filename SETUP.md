# ProTrader always-on setup (free)

GitHub Actions runs `cloud_job.py` 3 minutes after every hour (Sunday to Friday, UTC), even when your PC is off.
It emails new EURUSD signals / TP1 hits / closed trades, and uploads the signal page to traderpro.gamer.free.

## 1. GitHub account and private repository
1. Sign up at https://github.com (free).
2. Top right **+** -> **New repository**. Name: `protrader-cloud`. Choose **Private**. Do NOT add a README. Click **Create repository**.

## 2. Upload the code (PowerShell)
```
cd C:\Users\Tergel\Documents\ProTraderCloud
git remote add origin https://github.com/YOUR-USERNAME/protrader-cloud.git
git push -u origin main
```
A browser window asks you to sign in to GitHub - approve it.

## 3. Add the secrets
In the repository: **Settings -> Secrets and variables -> Actions -> New repository secret**. Add each one:

| Name | Value |
|---|---|
| GMAIL_USER | yellowtergel99@gmail.com |
| GMAIL_APP_PASSWORD | the 16-letter Gmail App Password |
| ALERT_EMAIL_TO | tergelerdene99999@gmail.com |
| ALERT_LOT | 0.02 |
| FTP_HOST | ftpupload.net |
| FTP_USER | if0_43246846 |
| FTP_PASSWORD | your InfinityFree hosting account password (InfinityFree -> Accounts -> if0_43246846 -> FTP Details) |
| PAGE_NAME | optional, see step 6 |

## 4. First run
**Actions** tab -> (enable workflows if asked) -> **EURUSD signals** -> **Run workflow**. After 1-2 minutes it shows a green tick.
A red cross means something is wrong: click it and read the last lines (wrong password, etc.).

## 5. Open the page
https://traderpro.gamer.free on your phone, iPad or laptop. A new domain can take up to 72 hours to work everywhere.
The page refreshes itself every 5 minutes; the data updates every hour.

## 6. Keep it private
- InfinityFree control panel -> **Password Protect Directories** -> choose `htdocs` -> set a username and password.
- If that option is missing: add the secret `PAGE_NAME` with a long random name such as `s-8kq2m7xw4p.html`. The page is then only at
  `https://traderpro.gamer.free/s-8kq2m7xw4p.html` - keep that link to yourself.

## 7. Stop the PC worker
Close `run_alerts.bat` on your PC once the cloud works - otherwise you get every email twice.

## Good to know
- Free: about 120 runs a week x ~1.5 min, well under GitHub's 2,000 free minutes a month for private repos.
- GitHub pauses scheduled jobs after 60 days without any change in the repository. It emails you first - then open
  the Actions tab and click **Enable**, or push any small change.
- After the plan changes on your PC: `.venv\Scripts\python sync_cloud.py` in ProTraderAI, then `git add -A`,
  `git commit -m "update"` and `git push` in ProTraderCloud.

## 8. The full app on your phone (Streamlit Community Cloud, free)
1. Open https://share.streamlit.io and **Continue with GitHub** (account Kanze9). Allow access to private repositories.
2. **Create app** -> **Deploy from GitHub**: Repository `Kanze9/protrader-cloud`, Branch `main`, Main file `app.py`.
   Pick a short App URL, e.g. `protrader-kanze`.
3. **Advanced settings**: Python 3.12. In **Secrets** paste (with your own key):
   ```
   DEEPSEEK_API_KEY = "your DeepSeek key"
   DEEPSEEK_BASE_URL = "https://tbnx.plus7.plus/v1"
   ```
4. **Deploy**. The first start takes 3-5 minutes (it installs everything).
5. Keep it private: the app's **Settings -> Sharing** -> only specific people -> add your own email.
   Apps from a private repository start private.
- On a phone the settings sidebar is behind the **»** button at the top left.
- After a few days without visits the app sleeps; opening it wakes it in about 30 seconds.
- If TradingView refuses the cloud server, the app falls back to Yahoo / other data and says so at the top.

## 9. On-time email alerts (optional, free): an outside timer
GitHub's free scheduler often skips runs (on 2026-10-26 it ran only every 3-6 hours), so emails can come late.
A free timer at cron-job.org can start the job every 30 minutes instead. You do these steps yourself (your accounts, your token):
1. GitHub -> your picture -> **Settings** -> **Developer settings** -> **Personal access tokens** -> **Fine-grained tokens** ->
   **Generate new token**. Name `cron`, expiration 1 year, **Only select repositories** -> `protrader-cloud`,
   **Repository permissions** -> **Actions: Read and write**. Generate and copy the token (keep it secret).
2. Make a free account at **cron-job.org** -> **Create cronjob**:
   - URL: `https://api.github.com/repos/Kanze9/protrader-cloud/actions/workflows/signals.yml/dispatches`
   - Schedule: every 30 minutes
   - **Advanced**: Request method **POST**; headers `Accept: application/vnd.github+json`,
     `Authorization: Bearer <your token>`, `X-GitHub-Api-Version: 2022-11-28`; request body `{"ref":"main"}`
3. Save and press **Test run**: GitHub -> Actions should show a new "workflow_dispatch" run within a few seconds.
4. Then remove the `schedule:` lines from `.github/workflows/signals.yml` (or keep them as a backup). At every 30 minutes the
   job uses about 1,460 of the 2,000 free GitHub minutes a month - don't go faster on a private repository.
