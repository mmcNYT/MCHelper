import faulthandler, sys
faulthandler.dump_traceback_later(25, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\maomaochongD\Coding\PythonProject\MCHelper")
import runpy
runpy.run_path(r"C:\maomaochongD\Coding\PythonProject\MCHelper\.temp\smoke_test_display_mode.py", run_name="__main__")
