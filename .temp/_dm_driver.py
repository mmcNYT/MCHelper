import faulthandler, sys, runpy, os
faulthandler.dump_traceback_later(25, exit=True)
sys.argv = ["smoke_test_display_mode.py"]
try:
    runpy.run_path(r".temp\smoke_test_display_mode.py", run_name="__main__")
    with open(r".temp\_dm_trace.txt", "a", encoding="utf-8") as f:
        f.write("COMPLETED-OK\n")
except BaseException as e:
    with open(r".temp\_dm_trace.txt", "a", encoding="utf-8") as f:
        f.write(f"EXC: {e!r}\n")
