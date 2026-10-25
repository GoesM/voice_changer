"""Cancelable subprocess jobs. Child output is retained locally for troubleshooting."""
import os
import subprocess
import threading


class Cancelled(RuntimeError):
    pass


class Job:
    def __init__(self):
        self.cancelled = threading.Event()
        self.process = None

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("操作已取消；素材和已完成的下载保留。")

    def cancel(self):
        self.cancelled.set()
        process = self.process
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.terminate()

    def run(self, args, cwd, progress, log, env=None):
        self.check()
        env = dict(os.environ if env is None else env, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(log, "a", encoding="utf-8") as output:
            output.write("\n> " + " ".join(map(str, args)) + "\n")
            self.process = subprocess.Popen(list(map(str, args)), cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=flags)
            try:
                if self.cancelled.is_set():
                    self.cancel()
                for line in self.process.stdout:
                    output.write(line)
                    output.flush()
                    progress(line.strip()[-350:])
                code = self.process.wait()
                self.check()
                if code:
                    raise RuntimeError(f"任务失败（退出码 {code}）。可打开本地日志查看原因。")
            finally:
                self.process.stdout.close()
                if self.process.poll() is None:
                    self.cancel()
                self.process = None
