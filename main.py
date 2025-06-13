import argparse
import subprocess
import sys

def run_command(cmd, description):
    print(f"\n🔧 {description}...")
    result = subprocess.run([sys.executable] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error running {description}")
        print(result.stderr)
        sys.exit(result.returncode)
    else:
        print(result.stdout)

def main():
    parser = argparse.ArgumentParser(description="Run FinOps RI Alert Pipeline")
    parser.add_argument(
        "--mode",
        choices=["all", "import", "analyze", "send"],
        default="all",
        help="Which stage to run: all | import | analyze | send"
    )

    args = parser.parse_args()

    if args.mode in ("all", "import"):
        run_command(["import_to_db.py", "--all"], "Import RI JSONs to DB")

    if args.mode in ("all", "analyze"):
        run_command(["analyze_ri_utilization.py"], "Analyze RI Utilization")

    if args.mode in ("all", "send"):
        run_command(["send_html_reports.py"], "Send Email Reports")

    print("✅ Done.")

if __name__ == "__main__":
    main()
