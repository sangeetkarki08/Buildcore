# BuildCore on the web, free: step-by-step guide

BuildCore web 2.35.0 is the same BuildCore you use on the desktop (same menus, screens, reports and figures),
but it runs on the internet. You open it in any browser, on a computer or a phone, from anywhere.

It uses three services. All three have a free plan and none asks for a card:

| Service | What it does for BuildCore | Free plan |
|---|---|---|
| **GitHub** | Keeps the program files | Free, private storage |
| **Supabase** | The database (your companies, vouchers, DPRs…) and the attachments | Free plan |
| **Vercel** | Runs the website | Free "Hobby" plan |

Setting it up takes about **45 minutes, once**. You need a Windows computer, an email address, and the file
`BuildCore_Web_2.35.0.zip`.

Keep **Notepad** open while you work: in Parts 2 and 4 you copy four values that you paste in Part 5.

---

## Before you start: what "free" means here (please read)

- **Good for testing and for a small team.** The free plans are enough for a few users entering DPRs,
  vouchers and reports every day.
- **Supabase free database: 500 MB**, file storage (photos, PDFs) **1 GB**, data downloads **5 GB a month**.
  A typical BuildCore company file is 5 to 50 MB, so the database is plenty; photos fill the 1 GB first.
- **Supabase pauses a free project after 7 days with nobody using it.** While paused the website shows
  an error. Nothing is lost: open <https://supabase.com/dashboard>, click the project, click **Restore**
  and wait 2 to 3 minutes. If someone uses BuildCore at least once a week, it never pauses.
- **Supabase free has no automatic backups.** Download a backup from BuildCore yourself (Part 9). This matters.
- **Vercel Hobby is for personal, non-commercial use** (Vercel's own rule). Testing is fine. When your company
  starts using it for real work, Vercel asks you to move to the **Pro** plan (about US$20 a month).
  Supabase's free plan has no such rule, but its paid **Pro** plan (about US$25 a month) removes the
  7-day pause and adds daily backups. You can upgrade either at any time; nothing needs to be set up again.
- **Vercel Hobby limits**: 1 million requests and 4 hours of processor time a month. A small team
  will not reach them. If you ever do, the site stops until the next month (or until you upgrade).

---

## Part 1. Make the three accounts (10 minutes)

1. **GitHub**: go to <https://github.com/signup>, enter your email, a password and a username. Confirm the
   code GitHub emails you.
2. **Vercel**: go to <https://vercel.com/signup>, choose **Hobby**, type your name, then click
   **Continue with GitHub** and allow it. (Signing up with GitHub saves a step later.)
3. **Supabase**: go to <https://supabase.com/dashboard/sign-up> and click **Continue with GitHub**.

## Part 2. Create the database in Supabase (5 minutes)

1. In <https://supabase.com/dashboard> click **New project**. If it asks for an organisation, accept the
   suggested one (plan: **Free**).
2. **Project name**: `buildcore`.
3. **Database password**: click **Generate a password**, then **Copy**, and paste it into Notepad as
   `PASSWORD = ...`. Supabase never shows it again.
4. **Region**: **South Asia (Mumbai)**. This matters: the website is set to run in Mumbai too, so they are close
   and every screen is quick.
5. Click **Create new project** and wait 1 to 2 minutes until it says the project is ready.

You do not need to create any tables. BuildCore creates them by itself the first time it starts.

## Part 3. Copy three values from Supabase (5 minutes)

**Value 1: DATABASE_URL** (where the database is)

1. In your project, click **Connect** at the top of the page.
2. Under **Connection String**, find **Session pooler** (not "Direct connection", not "Transaction pooler").
3. Copy the line under it. It looks like this:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres`
4. Paste it into Notepad. Replace `[YOUR-PASSWORD]` **including the square brackets** with your password
   from Part 2.
5. Check that it ends with **`:5432/postgres`**. If it shows 6543, you copied the Transaction pooler: go back
   and take Session pooler.

**Value 2: SUPABASE_URL** (the project's address)

- Click **Project Settings** (the gear at the bottom left) > **Data API**. Copy **Project URL**, like
  `https://abcdefgh.supabase.co`, into Notepad.

**Value 3: SUPABASE_SERVICE_ROLE_KEY** (the server's key to the file storage)

- **Project Settings** > **API Keys**. Either of these works:
  - tab **Legacy API keys**: the `service_role` key (marked *secret*), click **Reveal**, then copy; or
  - the **Secret keys** section: copy the key that starts with `sb_secret_`.
- Paste it into Notepad. **Keep this key private**: never send it to anyone or put it in a chat or email.
  BuildCore keeps it on the server only; it is never sent to browsers.

## Part 4. Put the program files on GitHub (10 minutes)

The easiest way on Windows is the free **GitHub Desktop** app (no typing commands):

1. Unzip `BuildCore_Web_2.35.0.zip` on your Desktop. You get a folder **`buildcore-web`**.
2. Download and install GitHub Desktop from <https://desktop.github.com>. Open it and sign in with your
   GitHub account.
3. **File > Add local repository…** > **Choose…** > select the `buildcore-web` folder on your Desktop.
   It says "This directory does not appear to be a Git repository": click **create a repository**.
4. Name `buildcore-web`, leave the rest, click **Create repository**.
5. Click **Publish repository** (top bar). **Keep "Keep this code private" ticked.** Click **Publish repository**.

After a minute your files are on GitHub, privately. (Uploading through the GitHub website also works,
but it takes at most 100 files at a time and this program has about 270, so GitHub Desktop is simpler.)

## Part 5. Create the website on Vercel (5 minutes)

1. Go to <https://vercel.com/new>. Under **Import Git Repository** find `buildcore-web` and click **Import**.
   (If it is not listed, click **Adjust GitHub App Permissions** and allow Vercel to see the repository.)
2. **Framework Preset**: choose **Other**. Do not change the Build and Output settings.
3. Open **Environment Variables** and add these four, one at a time (name on the left, value on the right,
   then **Add**):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Value 1 from Part 3 (with your real password, ending `:5432/postgres`) |
   | `SUPABASE_URL` | Value 2 from Part 3 |
   | `SUPABASE_SERVICE_ROLE_KEY` | Value 3 from Part 3 |
   | `BCO_SETUP_KEY` | Any words you choose, for example `hetauda-site-2026`. Write them in Notepad. |

4. Click **Deploy** and wait 1 to 2 minutes until you see "Congratulations".
5. Click **Continue to Dashboard**. Your web address is shown under **Domains**, like
   `buildcore-web-xyz.vercel.app`. That is your BuildCore. Save it as a bookmark.

The very first time you open it, it takes 10 to 20 seconds while BuildCore creates its tables.

## Part 6. Activate the licence (5 minutes)

The web edition is licensed like one more computer.

1. Open your web address. The page **Activate BuildCore** shows a **request code** (20 characters).
2. On your **admin computer** (the one that holds your master key), open BuildCore desktop >
   **Administration > Licence keys**. Enter the request code, the licensee, valid-until date and number of
   users, your master password, and make the key.
3. Copy the key, paste it into the web page and click **Activate**.

The key belongs to this Supabase project. If you ever create a new Supabase project, it needs a new key.

## Part 7. Create the first administrator (2 minutes)

The sign-in page now shows **Set up BuildCore**. Fill in your company name, a username and a password,
then click **Create administrator**. It asks for the **setup key**: type the `BCO_SETUP_KEY` words from Part 5.
(This stops a stranger who finds your address first from making themselves administrator.)

**For testing you can stop here** and start entering data. To work with your real desktop data, do Part 8.

## Part 8. Bring your desktop data across (nothing is lost)

1. On the **desktop**: **Administration > Backup & restore > Download a backup now**. You get a `.db` file.
2. On the **web**: **Administration > Backup & restore > Restore**, choose that file, click
   **Restore from file**, then **Restore**. It shows how many rows came across. Every record keeps its
   number: vouchers, DPRs, bills and ids are the same as on the desktop.
   The data that was on the web before is kept aside in the database, in case you need it.
3. **Sign in again with your desktop username and password.** (The administrator from Part 7 was only for
   getting in.)
4. **Photos and PDFs**: on the same page, **Attachments from BuildCore desktop** > choose the desktop's
   `data\files` folder (usually `C:\Users\<you>\AppData\Local\BuildCore\data\files`) > **Send the attachments**.
   It says how many were sent. If some failed, press it again; sending a file twice does no harm.
5. If you have **more than one company** on the desktop: on the web, create the company
   (**Administration > Companies**), switch to it, and do steps 1 to 4 for that company.

From now on, decide which one is "live": the web or the desktop. Entering on both at the same time makes
two different sets of books. To move back, do the same in the other direction (download a backup on the web,
restore it on the desktop).

## Part 9. Everyday use

- **Signing in**: everyone opens the web address and signs in with their own BuildCore user. Add users and
  give them projects in **Administration > Users and roles**, exactly as on the desktop.
- **On a phone**: open the address in Chrome, then menu **⋮ > Add to Home screen**. It opens like an app.
  DPR, store issues, logsheets and approvals work on the phone.
- **Backups (do this every week, and before big changes)**: **Administration > Backup & restore >
  Download a backup now**. Keep the `.db` files on your computer and in Google Drive or a USB drive.
  The file also opens in BuildCore desktop, so it is a full copy of your books.
- **If the site shows an error after a quiet week**: Supabase paused it. Open the Supabase dashboard,
  click the project, **Restore**, wait 3 minutes, reload BuildCore.
- **Your own address** (for example `erp.yourcompany.com`): Vercel > project > **Settings > Domains** > Add.
  It shows what to enter at your domain seller.

## Part 10. Updating to a new BuildCore version

When I send a new web version (a new `BuildCore_Web_<version>.zip`):

1. Unzip it. Copy everything **inside** its `buildcore-web` folder over your `buildcore-web` folder on the
   Desktop (choose **Replace the files**).
2. Open GitHub Desktop. It lists the changed files. Type a summary such as `BuildCore web 2.36.0`, click
   **Commit to main**, then **Push origin**.
3. Vercel sees the change and publishes the new version by itself in 1 to 2 minutes. On its first start
   BuildCore upgrades the database, exactly like the desktop updater upgrades your data file. Your data stays.

Take a backup (Part 9) before each update.

## If something goes wrong

| What you see | What to do |
|---|---|
| "The server sent an unexpected reply" or "Cannot reach BuildCore" on the first visit | Almost always the `DATABASE_URL`: the password is still `[YOUR-PASSWORD]`, the brackets were left in, or it is the Transaction pooler (6543). Fix it in Vercel > project > **Settings > Environment Variables**, then **Deployments** > ⋯ on the newest one > **Redeploy**. |
| The same error after a quiet week | Supabase paused the project: **Restore** it in the Supabase dashboard. |
| "File storage is not set up" when attaching a photo | `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is missing or wrong. Fix and redeploy as above. |
| "The setup key is not right" | Type exactly the `BCO_SETUP_KEY` words you put in Vercel. |
| Vercel says the build failed | Check that the folders `api`, `engine`, `public` and the file `vercel.json` are at the top of the GitHub repository (not inside another folder). |
| You want to see the exact reason | Vercel > project > **Logs**. Send me what it says (never send the keys). |

## What is different from the desktop

Very little; see `WEB_DIFFERENCES.md` in this folder. In short: data in Supabase instead of `data\buildcore.db`,
attachments and backups in Supabase Storage, no automatic daily backup by BuildCore (download it yourself),
document library search lists results newest first, and Team & devices / Remote access are not needed
(everyone simply opens the web address).
