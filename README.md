1. # FinOps RI Utilization Reporting Automation Project

   ## 1. Project Overview

   This project automates the analysis of Azure Reserved Instance (RI) utilization, generates comprehensive reports, and sends notifications to relevant stakeholders. Its primary goal is to help organizations optimize cloud costs by identifying underutilized, unused, or expiring RIs. By providing clear, actionable insights, it empowers FinOps teams and resource owners to make informed decisions about their reserved instance commitments.

   ## 2. Key Features

   - **Data Ingestion:** Fetches RI utilization data from a PostgreSQL database (or SQLite for local development).
   - **Utilization Analysis:** Analyzes RI utilization, identifies underutilized and unused RIs, and predicts upcoming expirations based on configurable thresholds.
   - **Alert Generation:** Generates concise alerts for RIs that are consistently underutilized, unused, or are nearing their expiration date.
   - **HTML Reporting:** Produces detailed and visually intuitive HTML reports with color-coded rows (healthy, underutilized, unused) for easy identification of RI health.
   - **CSV Reporting:** Generates recipient-specific CSV reports, providing granular data tailored to individual stakeholders for deeper analysis.
   - **Email Notifications:** Sends personalized email reports (HTML body with a recipient-specific CSV attachment) to designated recipients via Azure Logic App (for Azure deployment) or SMTP (for local development).
   - **Report Archiving:** Supports archiving generated reports (Excel, JSON, and recipient-specific CSVs) to Azure Blob Storage for historical tracking and auditing.

   - ## 3. Architecture Overview

     This project is designed to operate in two distinct modes: a local development environment and a production-ready Azure Functions deployment. While the core logic for analysis and reporting is consistent across both, the Azure architecture offers enhanced automation, scalability, and integration with cloud services.

     ### 3.1. Local Architecture

     The local setup is ideal for development, testing, and understanding the pipeline's mechanics without cloud dependencies.

     ```mermaid
     graph TD
         A[User/Developer] --> B(run_pipeline.sh);
         B --> C[query_azure_ri_data.py];
         C --> D[data/azure_ri_usage_daily_summary_YYYY-MM-DD.json];
         D --> E[import_to_db.py];
         E --> F[ri_data.db SQLite];
         F --> G[analyze_ri_utilization.py];
         G --> H[data/ri_utilization_summary_YYYY-MM-DD.json];
         H --> I[send_html_reports.py];
         I --> J[email_reports/HTML Reports];
         I --> K[email_reports/CSV Reports];
         I --> L[Local SMTP Server/Mock Service];
         L --> M[Email Recipients];
     
     ```

     ### 3.2. Azure Architecture (Recommended for Production)

     The Azure deployment leverages serverless Azure Functions to create a fully automated, event-driven pipeline, ensuring high availability, scalability, and seamless integration within the Azure ecosystem.

     ```mermaid
     graph TD
         A[Azure Cost Management Export] --> B(Azure Blob Storage: ri-raw-data);
     
         subgraph Azure Function App
             B -- New Blob --> C{import_to_db_func};
             C --> D[Azure PostgreSQL Database];
             D -- New Data --> E{analyze_ri_func};
             E --> F[Azure Blob Storage: ri-analysis-output JSON];
             E --> G[Azure Blob Storage: ri-archived-reports Excel];
             F -- New Blob --> H{send_reports_func};
             H --> I[Azure Blob Storage: ri-email-reports CSV];
             H --> J[Azure Logic App];
         end
     
         J --> K[Email Recipients];
     
         style A fill:#f9f,stroke:#333,stroke-width:2px;
         style B fill:#bbf,stroke:#333,stroke-width:2px;
         style D fill:#bbf,stroke:#333,stroke-width:2px;
         style F fill:#bbf,stroke:#333,stroke-width:2px;
         style G fill:#bbf,stroke:#333,stroke-width:2px;
         style I fill:#bbf,stroke:#333,stroke-width:2px;
         style J fill:#fbb,stroke:#333,stroke-width:2px;
         style K fill:#f9f,stroke:#333,stroke-width:2px;
     ```

## . Local Development and Execution

This section details how to set up and run the FinOps RI reporting pipeline in a local environment. The local setup's core logic (`analyze_ri_utilization.py`, `send_html_reports.py`) has been aligned with the Azure Functions version to ensure consistency in analysis and reporting.

### 4.1. Prerequisites

- **Python:** Version 3.10+

- **`pip`:** Python package installer

- **SQLite:** Used as a local database to simulate PostgreSQL.

- **Python Libraries:** Install dependencies from `requirements.txt`. It's recommended to create a Python virtual environment first:

  ```
  python3 -m venv .venv
  source .venv/bin/activate # On Windows: .venv\Scripts\activate
  pip install -r requirements.txt
  ```

### 4.2. Project Structure (Local)

The core files and directories for local execution are:

- `.env`: Environment variables for local configuration (database connection, email settings, thresholds).
- `main.py`: Orchestrates the local pipeline steps (`import`, `analyze`, `send`).
- `query_azure_ri_data.py`: (Mock Data Generation) Generates mock daily Azure RI utilization data and saves it as JSON files in the `data/` directory. **Note:** This script is a placeholder as direct Azure RI querying requires specific permissions not assumed for local setup.
- `import_to_db.py`: Imports the generated daily JSON data from `data/` into a local SQLite database (`ri_data.db`).
- `analyze_ri_utilization.py`: Processes data from `ri_data.db`, performs detailed RI utilization analysis (including consecutive days, missing data, and refined status classification), and outputs a summary JSON to `data/`. **This script's logic is consistent with the Azure Function version.**
- `send_html_reports.py`: Reads the analysis results from `data/`, generates visually enhanced HTML reports (with color-coded rows) and recipient-specific CSV reports, and saves them to `email_reports/`. It also handles email dispatch. **This script's logic is consistent with the Azure Function version.**
- `email_utils.py`: Contains utility functions for sending emails (supports SMTP for local testing).
- `email_test.py`: A simple script to test email sending functionality.
- `requirements.txt`: Lists all Python dependencies.
- `run_pipeline.sh`: A shell script to automate the local execution of the pipeline steps (on Linux/WSL/macOS).
- `data/`: Directory for input JSONs (from `query_azure_ri_data.py`) and output summary JSONs (from `analyze_ri_utilization.py`).
- `email_reports/`: Directory for generated HTML and CSV email reports.

### 4.3. Database Setup (Local SQLite)

For local development, an SQLite database (`ri_data.db`) is used to simulate a PostgreSQL database. The `analyze_ri_utilization.py` script is designed to connect to either based on the `DATABASE_CONNECTION_STRING` environment variable.

1. **Create the Database Table:** The `import_to_db.py` script automatically creates or updates the `ri_usage` table if it doesn't exist, ensuring its schema matches the expected daily granular data.

   ```
   CREATE TABLE IF NOT EXISTS ri_usage (
       subscription_id TEXT,
       resource_id TEXT,
       usage_quantity REAL,
       report_date TEXT,      -- Daily report date for this usage record
       email_recipient TEXT,
       sku_name TEXT,
       region TEXT,
       term_months INTEGER,
       purchase_date TEXT,    -- RI purchase date (fixed for an RI)
       PRIMARY KEY (subscription_id, resource_id, report_date)
   );
   ```

2. **Import Mock Data:** The `query_azure_ri_data.py` script generates mock daily data. To import this data into your local SQLite database:

   ```
   # First, generate the mock daily data
   python3 query_azure_ri_data.py
   # Then, import the generated data into SQLite
   python3 import_to_db.py --all
   ```

   It's recommended to delete the `ri_data.db` file before re-importing if you're making schema changes or want a fresh dataset.

### 4.4. Local Execution Steps

1. **Set Environment Variables:** Create a `.env` file in your project root with the following configuration. This file is crucial for the scripts to pick up necessary parameters.

   ```
   # Email sending method: choose between "smtp" or "logicapp"
   EMAIL_METHOD=smtp
   
   # Email credentials for SMTP mode (only used if EMAIL_METHOD=smtp)
   SMTP_USER=your_email@example.com
   SMTP_PASS=your_app_password
   SMTP_SERVER=smtp.example.com
   SMTP_PORT=587
   
   # Logic App endpoint for logicapp mode (only used if EMAIL_METHOD=logicapp)
   # For local testing, this can be left empty unless you have a local mock Logic App endpoint.
   LOGICAPP_ENDPOINT=
   
   # Utilization thresholds and analysis settings
   MIN_UTILIZATION_THRESHOLD=0.60
   EXPIRY_WARNING_DAYS=30
   UNDERUTILIZED_ALERT_DAYS=3
   UNUSED_ALERT_DAYS=5
   
   # Analysis source mode: "db" = use SQLite; "json" = use historical JSON files
   ANALYSIS_MODE=db
   # Database connection string for SQLite (for local development)
   DATABASE_CONNECTION_STRING=sqlite:///ri_data.db
   
   # Variables for local data generation and analysis consistency
   ANALYSIS_PERIOD_DAYS=30
   DEFAULT_REGION=eastus
   DEFAULT_SKU=Standard_DS1_v2
   MOCK_PURCHASE_DATE_OFFSET_DAYS=180
   
   # Email recipients for local reports
   EMAIL_RECIPIENTS=your.email@example.com
   EMAIL_SUBJECT_PREFIX="FinOps RI Report"
   RECIPIENT_EMAIL=default.recipient@example.com
   ```

   If you plan to test email sending locally, you might use a tool like [MailHog](https://github.com/mailhog/MailHog) (run `mailhog` in your terminal) and configure `SMTP_SERVER=localhost` and `SMTP_PORT=1025`.

2. **Run the Pipeline:** You can run the entire local pipeline using the provided shell script (recommended for Linux/WSL/macOS users):

   ```
   ./run_pipeline.sh
   ```

   This script will execute the steps sequentially: generate mock data, import to DB, analyze, and send reports.

   Alternatively, you can run individual stages using `main.py`:

   ```
   python3 main.py --mode import   # Generates mock data and imports to SQLite
   python3 main.py --mode analyze  # Analyzes data from SQLite and generates summary JSON
   python3 main.py --mode send     # Reads summary JSON, generates reports, and sends emails
   python3 main.py --mode all      # Runs all three modes sequentially
   ```

Upon successful execution, generated HTML and CSV reports will be found in the `email_reports/` directory. A summary JSON will be in `data/`. Emails will be dispatched via the configured SMTP server.

## 5. Azure Deployment (Recommended for Production)

The Azure Functions deployment offers a more robust, scalable, and automated solution compared to the local version, incorporating additional features and a more refined architecture.

### 5.1. Prerequisites

- **Azure Subscription:** An active Azure subscription.
- **Azure CLI:** Command-line interface for managing Azure resources. [Installation Guide](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
- **Terraform:** Infrastructure as Code tool for provisioning Azure resources. [Installation Guide](https://www.google.com/search?q=https://learn.hashicorp.com/terraform/install-cli)
- **Azure Functions Core Tools:** For local testing of Azure Functions and deploying to Azure. [Installation Guide](https://docs.microsoft.com/en-us/azure/azure-functions/functions-run-local)
- **Git:** Version control system.

### 5.2. Terraform Deployment (Infrastructure as Code)

Terraform is used to provision the necessary Azure resources for the FinOps RI Reporting Automation Project. The Terraform templates (typically found in a `terraform/` directory, though not provided in current context) will define the Azure Function App, Storage Account, Azure Database for PostgreSQL - Flexible Server, Azure Logic App, and other supporting resources.

1. **Clone the Repository:**

   ```
   git clone https://github.com/your-organization/finops-ri-reporting.git # Replace with your actual repo URL
   cd finops-ri-reporting
   # If Terraform files are in a subdirectory, navigate into it, e.g., cd terraform/
   ```

2. **Initialize Terraform:**

   ```
   terraform init
   ```

   This command initializes a working directory containing Terraform configuration files.

3. **Review the Plan:**

   ```
   terraform plan
   ```

   This command shows you which resources Terraform will create, modify, or destroy. Review it carefully before applying.

4. **Apply the Configuration:**

   ```
   terraform apply
   ```

   Confirm with `yes` when prompted. This will deploy the Azure infrastructure, including:

   - An Azure Function App (Python 3.10 runtime)
   - An Azure Storage Account (for Blob Storage and Queue Storage)
   - An Azure Database for PostgreSQL - Flexible Server
   - An Azure Logic App (for email sending)
   - Necessary App Service Plans, VNETs, etc.

5. **Configure Application Settings (Environment Variables) in Azure:** After Terraform deployment, you will need to set the following Application Settings (Environment Variables) in your deployed Azure Function App. These are crucial for the functions to connect to the database, storage, and Logic App. You can set these via the Azure Portal, Azure CLI, or PowerShell.

   - `POSTGRES_CONNECTION_STRING`: Connection string for your Azure PostgreSQL database. This will be provided by Terraform output or found in the Azure Portal.
     - Example: `Host=my-postgres-server.postgres.database.azure.com;Database=mydb;User=myuser;Password=mypassword;Port=5432;SslMode=Require;`
   - `AzureWebJobsStorage`: Connection string for your Azure Storage Account. This is typically automatically set by Azure Functions.
   - `LOGICAPP_ENDPOINT`: The HTTP POST URL of your deployed Azure Logic App. This will be obtained from the Logic App's HTTP Request trigger URL.
   - `EMAIL_RECIPIENTS`: Comma-separated list of email addresses for report recipients (e.g., `finops@example.com,manager@example.com`).
   - `EMAIL_SUBJECT_PREFIX`: Subject prefix for emails (e.g., `"FinOps RI Report"`).
   - `RI_ARCHIVED_REPORTS_CONTAINER`: Name of the blob container for archived Excel reports (e.g., `"ri-archived-reports"`).
   - `RI_EMAIL_REPORTS_CONTAINER`: Name of the blob container for archived email CSV reports (e.g., `"ri-email-reports"`).
   - `MIN_UTIL_THRESHOLD`: Minimum utilization percentage (e.g., `"0.8"` for 80%).
   - `EXPIRY_WARN_DAYS`: Days before expiry to warn (e.g., `"90"`).
   - `MIN_UNDERUTILIZED_DAYS_FOR_ALERT`: Consecutive underutilized days for alert (e.g., `"5"`).
   - `MIN_UNUSED_DAYS_FOR_ALERT`: Consecutive unused days for alert (e.g., `"3"`).
   - `ANALYSIS_PERIOD_DAYS`: Number of days for utilization analysis (e.g., `"30"`).
   - `DEFAULT_REGION`: Default region if not found in data (e.g., `"unknown"`).
   - `DEFAULT_SKU`: Default SKU if not found in data (e.g., `"unknown"`).
   - `RECIPIENT_EMAIL`: A fallback default email recipient for records without a specific tag (e.g., `"default.recipient@example.com"`).

### 5.3. Azure Functions Deployment

Deploy your Python Function App code to the Azure Function App provisioned by Terraform.

1. **Using Azure CLI:** Navigate to your project root directory (where `host.json` and your function folders like `import_to_db_func/`, `analyze_ri_func/`, `send_reports_func/` are located).

   ```
   func azure functionapp publish <YOUR_FUNCTION_APP_NAME> --python --build remote
   ```

   Replace `<YOUR_FUNCTION_APP_NAME>` with the name of your Function App. The `--build remote` flag is important for installing dependencies in Azure.

2. **Using VS Code Azure Tools:**

   - Install the Azure Functions extension from the VS Code Marketplace.
   - Open your project in VS Code.
   - In the Azure extension sidebar, sign in to your Azure account.
   - Find your Function App under "Functions" and right-click to select "Deploy to Function App...". Follow the prompts to deploy your project.

### 5.4. Azure Workflow (End-to-End Process)

The Azure deployment orchestrates the RI analysis pipeline using a series of interconnected Azure Functions, triggered by events in Blob Storage and Queue Storage.

1. **Data Source (Azure Cost Management Export):**
   - **Action:** Daily or weekly Azure Cost Management exports (e.g., utilization data for RIs) are configured within Azure to automatically drop CSV/JSON files into a specific Azure Blob Storage container (e.g., `ri-raw-data`).
   - **Purpose:** Provides the raw utilization data for the pipeline.
2. **`import_to_db_func` (Blob Trigger):**
   - **Trigger:** This Azure Function is triggered whenever a new RI utilization data file lands in the `ri-raw-data` Blob Storage container.
   - **Process:** It reads the raw data from the blob, processes it (e.g., parsing, cleaning), and imports it into the Azure PostgreSQL database. This function ensures daily granular utilization data is stored for historical analysis.
   - **Output:** Upon successful import, it sends a message to an Azure Queue Storage (e.g., `finops-ri-analysis-queue`) to trigger the next stage.
3. **`analyze_ri_func` (Queue Trigger):**
   - **Trigger:** This Azure Function is triggered by messages in the `finops-ri-analysis-queue`. Each message typically contains information about the newly imported data or the analysis period.
   - **Process:** It connects to the Azure PostgreSQL database, fetches the relevant RI utilization data for the specified analysis period (e.g., last 30 days). It then performs the core RI utilization analysis, identifying healthy, underutilized, unused, expiring, and missing data RIs, and calculates consecutive usage patterns. It also generates an Excel report.
   - **Output:** Both a detailed JSON summary of the analysis results and the Excel report are uploaded to designated Azure Blob Storage containers (e.g., `ri-analysis-output` for JSON, `ri-archived-reports` for Excel). Uploading the JSON summary to `ri-analysis-output` triggers the final reporting stage.
4. **`send_reports_func` (Blob Trigger):**
   - **Trigger:** This Azure Function is triggered when a new JSON summary file is uploaded to the `ri-analysis-output` Blob Storage container.
   - **Process:** It reads the JSON summary data. It groups the RI records by `email_recipient`. For each recipient, it generates a personalized HTML email body and a recipient-specific CSV attachment. The recipient-specific CSV is also archived to an Azure Blob Storage container (e.g., `ri-email-reports`) for auditing.
   - **Output:** Finally, it dispatches the email using the configured Azure Logic App endpoint. The Logic App then handles the actual sending of the email to the specified recipients.

## 6. Data Handling and Limitations

- **Mock Data Usage:**
  - This project was developed and tested extensively using `mock_data` due to the complexities of accessing live Azure Cost Management data during development.
  - The `query_azure_ri_data.py` script specifically generates this mock data.
  - **It is crucial to understand that `mock_data` is for demonstration and testing purposes only.** For production environments, you will need to integrate with a real Azure Cost Management export or API to feed actual RI utilization data into the pipeline.
- **`query` Function Limitations (for direct Azure API calls):**
  - The `query_azure_ri_data.py` script, while simulating data fetching, does not fully implement direct querying of Azure RI APIs (e.g., Azure Reservations API) due to the need for specific Azure permissions (e.g., `Microsoft.Consumption/usageDetails/read`, `Microsoft.Resources/subscriptions/resources/read`).
  - As we did not have the necessary permissions to create and manage RIs directly for testing, these direct API integration parts were not fully developed or tested.
  - Users deploying this project in a real Azure environment might need to implement or adapt the data ingestion process to directly query their Azure RI data based on their specific permissions and data sources.

## 7. Usage Guide / How It Works

This section provides a high-level overview of how to use and interact with the FinOps RI Reporting Automation Project once it's set up (either locally or in Azure).

1. **Configure Environment Variables:** Ensure all necessary environment variables are correctly set in your `.env` file (for local) or as Application Settings in your Azure Function App (for Azure). These variables control database connections, email settings, and analysis thresholds.
2. **Deploy (Azure) or Prepare (Local):**
   - **Azure:** Follow the Terraform deployment steps (Section 5.2) to provision the Azure infrastructure, then deploy the Azure Functions code (Section 5.3).
   - **Local:** Ensure all prerequisites are met, Python libraries are installed, and the local SQLite database is set up as described in Section 4.
3. **Data Ingestion:**
   - **Azure:** Configure your Azure Cost Management export to automatically drop RI utilization data files into the `ri-raw-data` Blob Storage container. The `import_to_db_func` will automatically pick up and process these files.
   - **Local:** Run `python3 query_azure_ri_data.py` to generate mock daily data, followed by `python3 import_to_db.py --all` to import it into your local SQLite database.
4. **Automated Analysis and Reporting:**
   - **Azure:** The pipeline is event-driven. Once data is ingested into the database, the `analyze_ri_func` and `send_reports_func` will be triggered automatically based on queue messages and blob uploads.
   - **Local:** Run `python3 main.py --mode analyze` followed by `python3 main.py --mode send` (or simply `./run_pipeline.sh`) to manually trigger the analysis and report generation/sending process.
5. **Receive Reports:** Designated email recipients will receive automated RI utilization reports in their inboxes, including the HTML summary and a detailed CSV attachment. Archived reports will be available in the configured Azure Blob Storage containers (for Azure deployment) or local `email_reports/` directory (for local runs).