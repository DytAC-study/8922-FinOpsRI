# RI Alerts Demo (CST8922 FinOps Project)

This project demonstrates an automated cost governance alert system for Reserved Instance (RI) underutilization in Microsoft Azure.

## Features

- Reads RI usage data via Azure Consumption API (or mock fallback)
- Identifies underutilized RIs (default threshold: 80%)
- Summarizes historical RI underuse (UnusedReservation cost)
- Generates HTML and CSV reports
- Sends real alert emails via Gmail SMTP
- Fully runnable in WSL or Ubuntu with Python venv

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

Edit `monitor_ri.py` and replace your subscription ID (if using real API):

```python
subscription_id = "your-subscription-id"
```

Then run:

```bash
python monitor_ri.py
# or
python summary.py
```

## Output

- HTML report in `/alerts/`
- CSV report in `/alerts/`
- Email alert via Gmail SMTP

## Optional Features

- Replace mock data with real Azure API
- Use Cost Management billing output
- Schedule via crontab or Azure Automation

## Authors

Team CST8922 - Azure FinOps Automation

------

# 📚 Data Model & FinOps Strategy

## 🔍 Where Mock Data Comes From

The mock data used in this project is modeled after **real Azure APIs**, specifically:

- **Azure Cost Management API** (`/query/usage`)
- **Azure Consumption API** (`reservation_usage_details`)
- **ChargeType == "UnusedReservation"`** represents money spent on Reserved Instances that were not used

We simulate:

- Daily RI usage records with quantity vs reserved quantity (monitor_ri.py)
- Cost Management billing records, including daily entries for ChargeType = "UnusedReservation" (parse_cost_details.py)

These mirror what you can get in a real production tenant, but allow us to demo logic without requiring actual RIs or enterprise cost access.

------

## 📈 What Azure Really Provides

Using Azure SDK or REST API, you can access:

- **Cost data** by:
  - Subscription
  - Resource Group
  - Service Name
  - Reservation ID
  - ChargeType (e.g. OnDemand, UnusedReservation)
  - Date
- **RI Usage data** by:
  - Instance ID
  - Quantity used
  - SKU name
  - Reservation duration

We query and group by these dimensions to simulate daily/monthly behavior.

------

## 💰 How This Helps Save Money

| Feature                 | Purpose                                                    | FinOps Impact                                                |
| ----------------------- | ---------------------------------------------------------- | ------------------------------------------------------------ |
| `monitor_ri.py`         | Detects low-utilization RIs (based on usage %)             | Prevents future waste by alerting early                      |
| `parse_cost_details.py` | Summarizes historical RI underuse (UnusedReservation cost) | Quantifies past financial waste to justify RI strategy changes |
| `summary.py`            | Merges both views                                          | Enables end-to-end visibility for IT + Finance teams         |



These reports can help:

- **Recommend reallocation** of RIs to other workloads
- **Trigger exchange/cancellation** actions if available
- **Inform future purchase decisions** ("Don't buy 1-yr RI for this SKU again")

------

## 📊 Daily vs. Monthly Tracking

| Type         | Tool                  | Insight                                    |
| ------------ | --------------------- | ------------------------------------------ |
| Daily usage  | monitor_ri.py         | Identifies real-time inefficiencies        |
| Monthly cost | parse_cost_details.py | Quantifies financial impact over time      |
| Combined     | summary.py            | Enables holistic reporting, trend analysis |



By tracking both **usage metrics** and **cost history**, the FinOps team can correlate technical and financial data to drive smarter cloud cost decisions.

------

# 📬 Email Notifications (Daily & Monthly)

The project includes full email functionality using **Gmail SMTP**, configured via environment variables.

## 🔐 Setup

First, enable 2-step verification on your Google account, and create an App Password.

Then, create a `.env` file in the root folder with:

```
SMTP_USER=your_gmail_account@gmail.com
SMTP_PASS=your_app_password_here
```

Install required packages:

```bash
pip install -r requirements.txt
```

## 🔔 Email Types

| Type               | Trigger                 | Purpose                                                      |
| ------------------ | ----------------------- | ------------------------------------------------------------ |
| **Daily Alert**    | `monitor_ri.py`         | RI instances with utilization below threshold (default 80%)  |
| **Monthly Report** | `parse_cost_details.py` | RI usage showing wasted cost from `UnusedReservation` entries |



## 📩 How to Use

No changes required — both scripts automatically send emails after generating results:

- HTML report is saved to `alerts/`
- CSV report is saved to `alerts/`
- Email is sent using Gmail SMTP with subject line and preview

## 💡 Email Functionality

Implemented in `email_utils.py`:

- `send_email(subject, html_body)` — sends a formatted HTML email
- `send_daily_alert_email(alerts)` — called by `monitor_ri.py`
- `send_monthly_cost_email(summary)` — called by `parse_cost_details.py`

Fallbacks (if email fails) will print content to the terminal.