"""Harbor adapter that drives ``eval/agent.py::chat``.

Only this file is added: ``agent.py`` keeps reading its own ``.env``, and runs in
the project's interpreter so Harbor's uv-tool environment needs no project deps
and no credentials.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

_EVAL_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _EVAL_DIR.parent
# _AGENT_PATH = _EVAL_DIR / "agent.py"
_AGENT_PATH = _EVAL_DIR / "chat_agent.py"
_VENV_PYTHON = _PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

# ``chat`` prints swallowed exceptions to stdout; everything the child writes is
# redirected so only the JSON line reaches the real stdout.
_INLINE = r'''
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

real_stdout = sys.stdout
buffer = io.StringIO()
out = {"text": "", "model": None, "base_url": None, "temperature": None,
       "error": None, "chat_stdout": ""}
try:
    root, agent_path = Path(sys.argv[1]), Path(sys.argv[2])
    sys.path.insert(0, str(root))
    with contextlib.redirect_stdout(buffer):
        spec = importlib.util.spec_from_file_location("agent_under_test", str(agent_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from deerflow_simple.config import SimpleConfig
        config = SimpleConfig.from_env()
        out["model"] = config.model.model
        out["base_url"] = config.model.base_url
        out["temperature"] = getattr(module.model, "temperature", None)
        answer = module.chat(sys.stdin.read())
        out["text"] = answer if isinstance(answer, str) else str(answer or "")
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {exc}"
finally:
    out["chat_stdout"] = buffer.getvalue().strip()[:2000]
    real_stdout.write(json.dumps(out, ensure_ascii=False))
'''


class NovelChatAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "novel-chat"

    def version(self) -> str | None:
        try:
            return hashlib.sha256(_AGENT_PATH.read_bytes()).hexdigest()
        except OSError:
            return None

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        proc = await asyncio.create_subprocess_exec(
            str(_VENV_PYTHON),
            "-c",
            _INLINE,
            str(_PROJECT_ROOT),
            str(_AGENT_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )
        stdout, stderr = await proc.communicate(instruction.encode("utf-8"))
        payload = self._decode(stdout, stderr)
        text = str(payload.get("text") or "")

        answer_path = self.logs_dir / "chat_answer.txt"
        answer_path.write_text(text, encoding="utf-8")
        await environment.upload_file(source_path=answer_path, target_path="/app/hello.txt")
        try:
            await environment.upload_file(
                source_path=answer_path, target_path="/logs/artifacts/answer.txt"
            )
        except Exception as exc:
            self.logger.warning("artifact upload skipped: %s", exc)

        base_url = payload.get("base_url")
        host = urlparse(base_url).hostname if isinstance(base_url, str) and base_url else None
        empty = not bool(text)
        context.metadata = {
            "agent_release": self.version(),
            "ds_model": payload.get("model"),
            "ds_base_url_host": host,
            "temperature": payload.get("temperature"),
            "session_id": self.session_id,
            "context_id": str(self.context_id) if self.context_id else None,
            "answer_chars": len(text),
            "chat_empty": empty,
            "chat_error": payload.get("error"),
            "chat_stdout": payload.get("chat_stdout") or None,
            "subprocess_exit_code": proc.returncode,
        }
        self.logger.info(
            "instruction_chars=%d answer_chars=%d chat_empty=%s",
            len(instruction), len(text), empty,
        )

    @staticmethod
    def _decode(stdout: bytes, stderr: bytes) -> dict:
        try:
            data = json.loads(stdout.decode("utf-8").strip())
            if isinstance(data, dict):
                return data
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {
            "text": "",
            "error": f"subprocess output: {stderr.decode('utf-8', 'replace').strip()[:500]}",
        }
