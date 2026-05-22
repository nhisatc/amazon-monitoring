"""
Entry point — runs both monitors.
Schedule this file with Windows Task Scheduler or Google Cloud Scheduler.

Suggested schedule:
  sales_monitor  → once daily at 8:00 AM
  review_monitor → every 2 hours
"""

import sys
import traceback
import sales_monitor
import review_monitor
import review_monitor_js


def safe_run(name, fn):
    print(f"\n{'='*50}")
    print(f"Running {name}…")
    print("=" * 50)
    try:
        fn()
    except Exception:
        print(f"ERROR in {name}:")
        traceback.print_exc()
        sys.exit(1)


safe_run("sales_monitor",     sales_monitor.run)
safe_run("review_monitor",    review_monitor.run)
safe_run("review_monitor_js", review_monitor_js.run)
print("\nAll monitors completed successfully.")
