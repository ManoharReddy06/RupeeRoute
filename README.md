# 🚀 RupeeRoute

A clean, modern, and intuitive personal, group sharing, and lending ledger web application built with **Django**, **SQLite (WAL Mode)**, and custom **Fintech CSS**.

---

## ⚡ How to Run

1. Open your terminal in this directory:
   ```powershell
   python manage.py runserver
   ```

2. Open your web browser:
   👉 **http://127.0.0.1:8000/**

---

## 🔑 Demo Logins (Available on Login Page)

1. **Active Personal Tracker Demo:**
   - **Username:** `manohar`
   - **Password:** `demo123`
   - *Displays an active profile, November 2026 pre-filled entries (`Curd`, `Rapido`, `Rent`, `Recharge`, `Dmart`, `Shopping`), category breakdown, and top card totals.*

2. **First-Time Profile Setup Test:**
   - **Username:** `admin`
   - **Password:** `admin123`
   - *Triggers the first-time profile setup wizard (Full Name, Age, Avatar/Photo).*

---

## 🎯 Features Implemented

1. **First-Time Login Setup:** Users are guided to enter their Full Name, Age, and optional profile photo/avatar.
2. **Top Period Selector:** Month & Year dropdown at the top dynamically filters expenses.
3. **Profile Card:**
   - Avatar / Photo (with fallback to colorful initials badge)
   - Full Name & Age
   - **Current Month Expense box** showing total amount paid till now in the selected month.
4. **Category Breakdown Section:**
   - Visual category cards with total spent, percentage of month, transaction count, and animated progress bars.
   - Handles standard and custom categories (*Food*, *Food/Curd*, *Travel*, *Rent*, *Shopping*, *Recharge*, etc.).
5. **Past Entries History Tab:**
   - Itemized transaction log (Date, Description, Category, Amount in ₹ INR, and Delete action).
   - **"➕ Enter New Spents"** button at the top right of the section to open the entry form.
6. **Instant Recalculation:**
   - Adding or deleting a spent entry immediately recalculates both the top Profile Card total and the Category Breakdown.

