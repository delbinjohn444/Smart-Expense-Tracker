"""
Expense Tracker — Flask Backend
======================================
Full-featured expense tracking system with:
  - SQLite via sqlite3 (no ORM overhead)
  - Dashboard stats & analytics
  - Full CRUD (Add / Edit / Delete)
  - Category + date range filtering
  - Monthly summary + top categories
  - Export to CSV
  - Budget alerts per category
  - JSON API endpoints for charts
"""

from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, make_response
)
import sqlite3, csv, io, json
from datetime import datetime, date, timedelta
from collections import defaultdict

app = Flask(__name__)
DB  = 'nexus.db'

# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def db():
    """Return a connected sqlite3 connection with Row factory."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create all tables on first run."""
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                amount      REAL    NOT NULL,
                category    TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                note        TEXT    DEFAULT '',
                payment     TEXT    DEFAULT 'Cash',
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS budgets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT    UNIQUE NOT NULL,
                monthly_limit REAL  NOT NULL
            );
        """)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

CATEGORIES = [
    'Food & Dining','Transport','Shopping','Entertainment',
    'Health & Medical','Utilities','Housing & Rent',
    'Education','Travel','Subscriptions','Investments','Other'
]

PAYMENTS = ['Cash','UPI','Credit Card','Debit Card','Net Banking','Wallet']

CATEGORY_ICONS = {
    'Food & Dining':'🍜','Transport':'🚗','Shopping':'🛍️',
    'Entertainment':'🎮','Health & Medical':'💊','Utilities':'⚡',
    'Housing & Rent':'🏠','Education':'📚','Travel':'✈️',
    'Subscriptions':'📡','Investments':'📈','Other':'📦'
}

# ──────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────

def parse_filters(args):
    """Extract and return filter params from query string."""
    return {
        'category' : args.get('category','').strip(),
        'payment'  : args.get('payment','').strip(),
        'date_from': args.get('date_from','').strip(),
        'date_to'  : args.get('date_to','').strip(),
        'search'   : args.get('search','').strip(),
        'sort'     : args.get('sort','date_desc'),
    }

def build_query(f):
    """Build SQL WHERE clause from filter dict."""
    clauses, params = ['1=1'], []
    if f['category']:
        clauses.append('category=?'); params.append(f['category'])
    if f['payment']:
        clauses.append('payment=?'); params.append(f['payment'])
    if f['date_from']:
        clauses.append('date>=?'); params.append(f['date_from'])
    if f['date_to']:
        clauses.append('date<=?'); params.append(f['date_to'])
    if f['search']:
        clauses.append('(title LIKE ? OR note LIKE ?)')
        params += [f'%{f["search"]}%', f'%{f["search"]}%']
    return ' AND '.join(clauses), params

SORT_MAP = {
    'date_desc':'date DESC, id DESC', 'date_asc':'date ASC, id ASC',
    'amount_desc':'amount DESC',      'amount_asc':'amount ASC',
    'title_asc':'title ASC',
}

def get_monthly_stats(conn, year=None, month=None):
    """Return total, count, avg for a given month (default = current)."""
    today = date.today()
    y = year  or today.year
    m = month or today.month
    prefix = f'{y}-{m:02d}'
    row = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS cnt, "
        "COALESCE(AVG(amount),0) AS avg FROM expenses WHERE date LIKE ?",
        (f'{prefix}%',)
    ).fetchone()
    return dict(row)

def get_category_totals(conn, date_from=None, date_to=None):
    """Return per-category totals for the current month by default."""
    today = date.today()
    df = date_from or f'{today.year}-{today.month:02d}-01'
    dt = date_to   or today.isoformat()
    rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        "WHERE date BETWEEN ? AND ? GROUP BY category ORDER BY total DESC",
        (df, dt)
    ).fetchall()
    return [dict(r) for r in rows]

# ──────────────────────────────────────────────
# Routes — Pages
# ──────────────────────────────────────────────

@app.route('/')
def dashboard():
    """Main dashboard with stats, charts data, recent transactions."""
    f    = parse_filters(request.args)
    wher, params = build_query(f)
    sort = SORT_MAP.get(f['sort'], 'date DESC, id DESC')

    with db() as conn:
        # Filtered expenses
        expenses = conn.execute(
            f'SELECT * FROM expenses WHERE {wher} ORDER BY {sort}',
            params
        ).fetchall()

        # Total (filtered)
        total_filtered = conn.execute(
            f'SELECT COALESCE(SUM(amount),0) FROM expenses WHERE {wher}',
            params
        ).fetchone()[0]

        # This month stats
        month_stats = get_monthly_stats(conn)

        # Last month for comparison
        today = date.today()
        if today.month == 1:
            last = get_monthly_stats(conn, today.year-1, 12)
        else:
            last = get_monthly_stats(conn, today.year, today.month-1)

        # Category breakdown (this month)
        cat_totals = get_category_totals(conn)

        # Budgets
        budgets = {r['category']: r['monthly_limit']
                   for r in conn.execute('SELECT * FROM budgets').fetchall()}

        # All-time total
        all_time = conn.execute(
            'SELECT COALESCE(SUM(amount),0) FROM expenses'
        ).fetchone()[0]

        # Top spending day this month
        top_day = conn.execute(
            "SELECT date, SUM(amount) AS total FROM expenses "
            "WHERE date LIKE ? GROUP BY date ORDER BY total DESC LIMIT 1",
            (f'{today.year}-{today.month:02d}%',)
        ).fetchone()

        # Daily trend last 30 days
        trend = conn.execute(
            "SELECT date, SUM(amount) AS total FROM expenses "
            "WHERE date >= ? GROUP BY date ORDER BY date ASC",
            ((today - timedelta(days=29)).isoformat(),)
        ).fetchall()

    # Month-over-month change
    mom_change = 0
    if last['total'] > 0:
        mom_change = ((month_stats['total'] - last['total']) / last['total']) * 100

    return render_template('dashboard.html',
        expenses=expenses,
        total_filtered=total_filtered,
        month_stats=month_stats,
        last_month=last,
        mom_change=round(mom_change, 1),
        cat_totals=cat_totals,
        budgets=budgets,
        all_time=all_time,
        top_day=top_day,
        trend_data=json.dumps([{'date':r['date'],'total':r['total']} for r in trend]),
        cat_data=json.dumps(cat_totals),
        categories=CATEGORIES,
        payments=PAYMENTS,
        category_icons=CATEGORY_ICONS,
        filters=f,
        today=today.isoformat(),
    )


@app.route('/add', methods=['GET','POST'])
def add_expense():
    """Add a new expense."""
    errors = []
    form   = {}

    if request.method == 'POST':
        form = request.form.to_dict()
        title    = form.get('title','').strip()
        amount   = form.get('amount','').strip()
        category = form.get('category','').strip()
        exp_date = form.get('date','').strip()
        note     = form.get('note','').strip()
        payment  = form.get('payment','Cash').strip()

        if not title:             errors.append('Title is required.')
        if not category:          errors.append('Category is required.')
        if not exp_date:          errors.append('Date is required.')
        try:
            amount = float(amount)
            if amount <= 0: raise ValueError
        except (ValueError, TypeError):
            errors.append('Amount must be a positive number.')

        if not errors:
            with db() as conn:
                conn.execute(
                    'INSERT INTO expenses (title,amount,category,date,note,payment) '
                    'VALUES (?,?,?,?,?,?)',
                    (title, amount, category, exp_date, note, payment)
                )
            return redirect(url_for('dashboard'))

    return render_template('add.html',
        categories=CATEGORIES, payments=PAYMENTS,
        errors=errors, form=form,
        today=date.today().isoformat(),
        category_icons=CATEGORY_ICONS,
    )


@app.route('/edit/<int:eid>', methods=['GET','POST'])
def edit_expense(eid):
    """Edit an existing expense."""
    errors = []
    with db() as conn:
        expense = conn.execute('SELECT * FROM expenses WHERE id=?', (eid,)).fetchone()
    if not expense:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        form     = request.form.to_dict()
        title    = form.get('title','').strip()
        amount   = form.get('amount','').strip()
        category = form.get('category','').strip()
        exp_date = form.get('date','').strip()
        note     = form.get('note','').strip()
        payment  = form.get('payment','Cash').strip()

        if not title:    errors.append('Title is required.')
        if not category: errors.append('Category is required.')
        if not exp_date: errors.append('Date is required.')
        try:
            amount = float(amount)
            if amount <= 0: raise ValueError
        except (ValueError, TypeError):
            errors.append('Amount must be a positive number.')

        if not errors:
            with db() as conn:
                conn.execute(
                    'UPDATE expenses SET title=?,amount=?,category=?,date=?,note=?,payment=? WHERE id=?',
                    (title, amount, category, exp_date, note, payment, eid)
                )
            return redirect(url_for('dashboard'))

        expense = dict(expense)
        expense.update(form)
    else:
        expense = dict(expense)

    return render_template('edit.html',
        expense=expense, categories=CATEGORIES,
        payments=PAYMENTS, errors=errors,
        category_icons=CATEGORY_ICONS,
    )


@app.route('/delete/<int:eid>', methods=['POST'])
def delete_expense(eid):
    with db() as conn:
        conn.execute('DELETE FROM expenses WHERE id=?', (eid,))
    return redirect(url_for('dashboard'))


@app.route('/budgets', methods=['GET','POST'])
def budgets():
    """Manage per-category monthly budgets."""
    msg = ''
    if request.method == 'POST':
        category = request.form.get('category','').strip()
        limit    = request.form.get('limit','').strip()
        try:
            limit = float(limit)
            if limit <= 0: raise ValueError
        except (ValueError, TypeError):
            msg = 'error'
        else:
            with db() as conn:
                conn.execute(
                    'INSERT INTO budgets (category, monthly_limit) VALUES (?,?) '
                    'ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit',
                    (category, limit)
                )
            msg = 'saved'

    today = date.today()
    with db() as conn:
        budget_rows = conn.execute('SELECT * FROM budgets ORDER BY category').fetchall()
        cat_spend   = {r['category']: r['total'] for r in conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses "
            "WHERE date LIKE ? GROUP BY category",
            (f'{today.year}-{today.month:02d}%',)
        ).fetchall()}

    budget_data = []
    for b in budget_rows:
        spent = cat_spend.get(b['category'], 0)
        pct   = min(round((spent / b['monthly_limit']) * 100), 100) if b['monthly_limit'] else 0
        budget_data.append({
            'category': b['category'],
            'limit'   : b['monthly_limit'],
            'spent'   : spent,
            'pct'     : pct,
            'status'  : 'danger' if pct >= 90 else ('warn' if pct >= 70 else 'ok')
        })

    return render_template('budgets.html',
        budget_data=budget_data, categories=CATEGORIES,
        category_icons=CATEGORY_ICONS, msg=msg,
    )


@app.route('/delete_budget/<category>', methods=['POST'])
def delete_budget(category):
    with db() as conn:
        conn.execute('DELETE FROM budgets WHERE category=?', (category,))
    return redirect(url_for('budgets'))


@app.route('/export/csv')
def export_csv():
    """Download all expenses (or filtered) as CSV."""
    f = parse_filters(request.args)
    wher, params = build_query(f)
    with db() as conn:
        rows = conn.execute(
            f'SELECT id,date,title,category,amount,payment,note FROM expenses '
            f'WHERE {wher} ORDER BY date DESC', params
        ).fetchall()

    si = io.StringIO()
    w  = csv.writer(si)
    w.writerow(['ID','Date','Title','Category','Amount (INR)','Payment','Note'])
    for r in rows:
        w.writerow(list(r))

    output = make_response(si.getvalue())
    output.headers['Content-Disposition'] = 'attachment; filename=nexus_expenses.csv'
    output.headers['Content-type']        = 'text/csv'
    return output


# ──────────────────────────────────────────────
# JSON API (for charts)
# ──────────────────────────────────────────────

@app.route('/api/trend')
def api_trend():
    """Daily totals for the last N days."""
    days  = int(request.args.get('days', 30))
    today = date.today()
    since = (today - timedelta(days=days-1)).isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT date, SUM(amount) AS total FROM expenses "
            "WHERE date>=? GROUP BY date ORDER BY date ASC", (since,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/categories')
def api_categories():
    """Category totals for the current month."""
    today = date.today()
    with db() as conn:
        rows = get_category_totals(conn)
    return jsonify(rows)


# ──────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    app.run(debug=True)