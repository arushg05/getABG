"""
getABG Strategy Sandbox
Implements the Host-Guest isolation model from SRS §1.
Strategies run in an isolated subprocess with configurable timeout.
The Host communicates via JSON payloads written to stdin/read from stdout.
"""

import sys
import os
import json
import subprocess
import tempfile
import textwrap
import time
import traceback
from typing import Dict, Any, Optional, List

DEFAULT_TIMEOUT_MS = 5000  # 5 seconds per tick

RUNNER_TEMPLATE = '''
import sys
import json
import traceback

# === GUEST STRATEGY RUNNER ===
# Injected by getABG sandbox at runtime.
# Loads user strategy and runs the tick loop.

{strategy_code}

def _run():
    strategy_instance = None
    
    # Strategy must define a class named 'Strategy'
    if 'Strategy' not in globals():
        print(json.dumps({{"error": "No Strategy class found in strategy file"}}))
        sys.exit(1)
    
    strategy_instance = Strategy()
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "__DONE__":
            break
        try:
            payload = json.loads(line)
            
            if payload.get("_cmd") == "INIT":
                if hasattr(strategy_instance, 'on_init'):
                    strategy_instance.on_init(payload.get("params", {{}}))
                response = {{"heartbeat": True, "action_queue": []}}
            else:
                result = strategy_instance.on_tick(
                    payload["timestamp"],
                    payload["market_state"],
                    payload["portfolio_state"],
                )
                if result is None:
                    result = []
                elif isinstance(result, dict):
                    result = [result]
                response = {{"heartbeat": True, "action_queue": result}}
            
            print(json.dumps(response), flush=True)
        except Exception as e:
            err_resp = {{
                "heartbeat": False,
                "action_queue": [],
                "error": str(e),
                "traceback": traceback.format_exc()
            }}
            print(json.dumps(err_resp), flush=True)

_run()
'''


class SandboxViolation(Exception):
    """Raised when strategy violates sandbox contract."""
    pass


class StrategyWorker:
    """
    Manages a sandboxed strategy subprocess.
    Enforces the Host-Guest contract from SRS §3.
    """

    def __init__(
        self,
        strategy_path: str,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        verbose: bool = False,
    ):
        self.strategy_path = strategy_path
        self.timeout_ms = timeout_ms
        self.verbose = verbose
        self._proc: Optional[subprocess.Popen] = None
        self._runner_file = None

    def start(self, init_params: dict = None):
        """Launch the strategy subprocess."""
        with open(self.strategy_path, "r") as f:
            strategy_code = f.read()

        runner_code = RUNNER_TEMPLATE.format(strategy_code=strategy_code)

        # Write runner to temp file
        self._runner_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, prefix="getabg_worker_"
        )
        self._runner_file.write(runner_code)
        self._runner_file.close()

        self._proc = subprocess.Popen(
            [sys.executable, self._runner_file.name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # Send INIT command
        init_payload = {"_cmd": "INIT", "params": init_params or {}}
        self._send(init_payload)
        resp = self._recv()
        if "error" in resp:
            raise SandboxViolation(f"Strategy initialization failed: {resp['error']}")
        if self.verbose:
            print(f"  [Sandbox] Worker started. Init response: {resp}")
        return resp

    def tick(self, timestamp: str, market_state: dict, portfolio_state: dict) -> Dict:
        """
        Send a market tick to the strategy and receive the response.
        Enforces timeout per SRS §4 Guest Process Timeout.
        """
        if not self._proc or self._proc.poll() is not None:
            stderr_content = ""
            if self._proc:
                try:
                    stderr_content = self._proc.stderr.read()
                except Exception:
                    pass
            err_msg = "Strategy process has terminated unexpectedly."
            if stderr_content:
                err_msg += f"\nProcess stderr:\n{stderr_content}"
            raise SandboxViolation(err_msg)

        payload = {
            "timestamp": timestamp,
            "market_state": market_state,
            "portfolio_state": portfolio_state,
        }
        self._send(payload)
        return self._recv()

    def _send(self, payload: dict):
        data = json.dumps(payload) + "\n"
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except BrokenPipeError:
            raise SandboxViolation("Strategy process pipe broken (process may have crashed).")

    def _recv(self) -> Dict:
        """Read one JSON response line with timeout enforcement."""
        import select, platform
        timeout_sec = self.timeout_ms / 1000.0
        start = time.time()

        # Non-blocking readline with timeout
        if platform.system() != "Windows":
            ready, _, _ = select.select([self._proc.stdout], [], [], timeout_sec)
            if not ready:
                self.terminate()
                raise TimeoutError(
                    f"Strategy timed out after {self.timeout_ms}ms. "
                    "Possible infinite loop or heavy computation."
                )
            line = self._proc.stdout.readline()
        else:
            # Windows fallback: threaded read
            import threading
            result = [None]
            def reader():
                result[0] = self._proc.stdout.readline()
            t = threading.Thread(target=reader, daemon=True)
            t.start()
            t.join(timeout_sec)
            if result[0] is None:
                self.terminate()
                raise TimeoutError(f"Strategy timed out after {self.timeout_ms}ms.")
            line = result[0]

        if not line:
            stderr_content = ""
            if self._proc:
                try:
                    stderr_content = self._proc.stderr.read()
                except Exception:
                    pass
            err_msg = "Strategy process returned empty response."
            if stderr_content:
                err_msg += f"\nProcess stderr:\n{stderr_content}"
            raise SandboxViolation(err_msg)

        try:
            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            raise SandboxViolation(f"Strategy returned invalid JSON: {line!r} | {e}")

    def terminate(self):
        """Gracefully terminate the worker process."""
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write("__DONE__\n")
                self._proc.stdin.flush()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()

        if self._runner_file:
            try:
                os.unlink(self._runner_file.name)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.terminate()


def validate_action_queue(action_queue: List[dict]) -> List[dict]:
    """
    Validate and sanitize orders from the Guest response.
    Ensures each order has required fields before it reaches the portfolio engine.
    """
    valid_actions = []
    for order in action_queue:
        if not isinstance(order, dict):
            continue
        if "ticker" not in order or "action" not in order:
            continue
        if order.get("action") not in ("BUY", "SELL"):
            continue
        quantity = order.get("quantity")
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            continue
        order_type = order.get("order_type", "MARKET")
        if order_type not in ("MARKET", "LIMIT", "STOP"):
            order["order_type"] = "MARKET"
        valid_actions.append(order)
    return valid_actions
