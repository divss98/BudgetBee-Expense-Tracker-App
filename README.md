# BudgetBee 🐝

BudgetBee is a clean, local-first expense tracker built with Streamlit. It helps you log spending quickly, understand where your money goes, and stay on top of a monthly budget—with Groq AI for natural-language expense entry and spending insights.

###### This project was developed as part of the Week1 Project of the Mastering Agentic AI Course by The Gen Academy.

## Features

- Natural-language expense logging powered by Groq. Enter one or more expenses such as `Spent $42 on gas yesterday` or `Coffee at Starbucks $6.50`.
- Intelligent extraction of date, amount, description, and category.
- Bulk CSV import and CSV export.
- Editable expense table for making quick corrections.
- Dashboard-wide sidebar filters for date ranges and categories.
- Spending metrics, budget progress, category nudges, and fixed-cost tracking.
- Five default-currency choices with current-rate conversion for saved expenses, budgets, and AI entries.
- Analytics with category breakdown, daily spending trends, biggest purchases, and concise AI spending highlights.
- Local JSON storage—no database setup required.

## Tech stack

- Python and Streamlit
- Groq API for AI parsing and spending summaries
- Pandas for data handling
- Plotly for charts

## Project structure

```text
BudgetBee-Expense-Tracker-App/
├── app.py                 # Streamlit application entry point
├── utils/
│   ├── data_manager.py    # Local storage, CSV, and budget helpers
│   └── expense_ai.py      # Groq-powered expense and insight logic
│   └── currency.py        # Curreny exchange converting logic using Frankfurter API
├── data/                  # Local expense and settings data (ignored by Git)
├── .env.example           # Environment variable template
└── requirements.txt       # Python dependencies
```

## Setup

### 1. Clone the project and enter its folder

```bash
git clone <your-repository-url>
cd BudgetBee-Expense-Tracker-App
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Groq

Copy the template and add your Groq API key:

```bash
cp .env.example .env
```

Then update `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Get a Groq API key from [Groq Console](https://console.groq.com/keys). The `.env` file is ignored by Git, so do not commit it.

Groq is optional: without a key, BudgetBee uses a basic local parser for simple entries. AI-generated multi-expense parsing and analytics highlights require the key.

Currency conversion uses the latest published rate from the [Frankfurter API](https://frankfurter.dev/) and needs an internet connection when a conversion is required.

### 5. Start the app

```bash
streamlit run app.py
```

Open the local URL shown in your terminal, typically `http://localhost:8501`.

## CSV import format

Upload a CSV with the following headers:

```csv
date,category,description,amount
2026-08-13,Dining,Coffee at Starbucks,6.50
2026-08-12,Transport,Gas station,42.00
```

Supported categories are: `Dining`, `Groceries`, `Transport`, `Shopping`, `Utilities`, `Entertainment`, and `Other`.

## Data and privacy

Expenses and the monthly budget are saved locally in `data/expenses.json` and `data/settings.json`. Both files are ignored by Git. You can download your expense data as CSV or clear it from the Settings tab at any time.
