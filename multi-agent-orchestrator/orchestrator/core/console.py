import asyncio
import itertools
import sys


class Spinner:
    def __init__(self, message="진행 중..."):
        self.message = message
        self.is_running = False
        self.task = None

    async def _spin(self):
        spinner_chars = itertools.cycle(
            ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        try:
            while self.is_running:
                sys.stdout.write(
                    f"\r\033[96m[{next(spinner_chars)}]\033[0m "
                    f"{self.message} "
                )
                sys.stdout.flush()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def start(self):
        self.is_running = True
        self.task = asyncio.create_task(self._spin())

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        sys.stdout.write(f"\r\033[92m[✔]\033[0m {self.message} 완료!       \n")
        sys.stdout.flush()
