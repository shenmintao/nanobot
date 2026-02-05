"""OpenAI Codex OAuth implementation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

import httpx

from nanobot.utils.helpers import ensure_dir, get_data_path

# Fixed parameters (sourced from the official Codex CLI OAuth client).
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
REDIRECT_URI = "http://localhost:1455/auth/callback"
SCOPE = "openid profile email offline_access"
JWT_CLAIM_PATH = "https://api.openai.com/auth"

DEFAULT_ORIGINATOR = "nanobot"
TOKEN_FILENAME = "codex.json"
MANUAL_PROMPT_DELAY_SEC = 3
SUCCESS_HTML = (
    "<!doctype html>"
    "<html lang=\"en\">"
    "<head>"
    "<meta charset=\"utf-8\" />"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
    "<title>Authentication successful</title>"
    "</head>"
    "<body>"
    "<p>Authentication successful. Return to your terminal to continue.</p>"
    "</body>"
    "</html>"
)


@dataclass
class CodexToken:
    """Codex OAuth token data structure."""
    access: str
    refresh: str
    expires: int
    account_id: str


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _decode_base64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _generate_pkce() -> tuple[str, str]:
    verifier = _base64url(os.urandom(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


def _create_state() -> str:
    return _base64url(os.urandom(16))


def _get_token_path() -> Path:
    auth_dir = ensure_dir(get_data_path() / "auth")
    return auth_dir / TOKEN_FILENAME


def _parse_authorization_input(raw: str) -> tuple[str | None, str | None]:
    value = raw.strip()
    if not value:
        return None, None
    try:
        url = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(url.query)
        code = qs.get("code", [None])[0]
        state = qs.get("state", [None])[0]
        if code:
            return code, state
    except Exception:
        pass

    if "#" in value:
        parts = value.split("#", 1)
        return parts[0] or None, parts[1] or None

    if "code=" in value:
        qs = urllib.parse.parse_qs(value)
        return qs.get("code", [None])[0], qs.get("state", [None])[0]

    return value, None


def _decode_account_id(access_token: str) -> str:
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT token")
    payload = json.loads(_decode_base64url(parts[1]).decode("utf-8"))
    auth = payload.get(JWT_CLAIM_PATH) or {}
    account_id = auth.get("chatgpt_account_id")
    if not account_id:
        raise ValueError("Failed to extract account_id from token")
    return str(account_id)


class _OAuthHandler(BaseHTTPRequestHandler):
    """Local callback HTTP handler."""

    server_version = "NanobotOAuth/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        try:
            url = urllib.parse.urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            qs = urllib.parse.parse_qs(url.query)
            code = qs.get("code", [None])[0]
            state = qs.get("state", [None])[0]

            if state != self.server.expected_state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch")
                return

            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code")
                return

            self.server.code = code
            try:
                if getattr(self.server, "on_code", None):
                    self.server.on_code(code)
            except Exception:
                pass
            body = SUCCESS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            try:
                self.wfile.flush()
            except Exception:
                pass
            self.close_connection = True
        except Exception:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal error")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Suppress default logs to avoid noisy output.
        return


class _OAuthServer(HTTPServer):
    """OAuth callback server with state."""

    def __init__(
        self,
        server_address: tuple[str, int],
        expected_state: str,
        on_code: Callable[[str], None] | None = None,
    ):
        super().__init__(server_address, _OAuthHandler)
        self.expected_state = expected_state
        self.code: str | None = None
        self.on_code = on_code


def _start_local_server(
    state: str,
    on_code: Callable[[str], None] | None = None,
) -> tuple[_OAuthServer | None, str | None]:
    """Start a local OAuth callback server on the first available localhost address."""
    try:
        addrinfos = socket.getaddrinfo("localhost", 1455, type=socket.SOCK_STREAM)
    except OSError as exc:
        return None, f"Failed to resolve localhost: {exc}"

    last_error: OSError | None = None
    for family, _socktype, _proto, _canonname, sockaddr in addrinfos:
        try:
            # 兼容 IPv4/IPv6 监听，避免 localhost 解析到 ::1 时收不到回调
            class _AddrOAuthServer(_OAuthServer):
                address_family = family

            server = _AddrOAuthServer(sockaddr, state, on_code=on_code)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            return server, None
        except OSError as exc:
            last_error = exc
            continue

    if last_error:
        return None, f"Local callback server failed to start: {last_error}"
    return None, "Local callback server failed to start: unknown error"


def _exchange_code_for_token(code: str, verifier: str) -> CodexToken:
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {response.status_code} {response.text}")

    payload = response.json()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, int):
        raise RuntimeError("Token response missing fields")
    print("Received access token:", access)
    account_id = _decode_account_id(access)
    return CodexToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000 + expires_in * 1000),
        account_id=account_id,
    )


async def _exchange_code_for_token_async(code: str, verifier: str) -> CodexToken:
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {response.status_code} {response.text}")

    payload = response.json()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, int):
        raise RuntimeError("Token response missing fields")

    account_id = _decode_account_id(access)
    return CodexToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000 + expires_in * 1000),
        account_id=account_id,
    )


def _refresh_token(refresh_token: str) -> CodexToken:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if response.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {response.status_code} {response.text}")

    payload = response.json()
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not access or not refresh or not isinstance(expires_in, int):
        raise RuntimeError("Token refresh response missing fields")

    account_id = _decode_account_id(access)
    return CodexToken(
        access=access,
        refresh=refresh,
        expires=int(time.time() * 1000 + expires_in * 1000),
        account_id=account_id,
    )


def _load_token_file() -> CodexToken | None:
    path = _get_token_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CodexToken(
            access=data["access"],
            refresh=data["refresh"],
            expires=int(data["expires"]),
            account_id=data["account_id"],
        )
    except Exception:
        return None


def _save_token_file(token: CodexToken) -> None:
    path = _get_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "access": token.access,
                "refresh": token.refresh,
                "expires": token.expires,
                "account_id": token.account_id,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except Exception:
        # Ignore permission setting failures.
        pass


def _try_import_codex_cli_token() -> CodexToken | None:
    codex_path = Path.home() / ".codex" / "auth.json"
    if not codex_path.exists():
        return None
    try:
        data = json.loads(codex_path.read_text(encoding="utf-8"))
        tokens = data.get("tokens") or {}
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        account_id = tokens.get("account_id")
        if not access or not refresh or not account_id:
            return None
        try:
            mtime = codex_path.stat().st_mtime
            expires = int(mtime * 1000 + 60 * 60 * 1000)
        except Exception:
            expires = int(time.time() * 1000 + 60 * 60 * 1000)
        token = CodexToken(
            access=str(access),
            refresh=str(refresh),
            expires=expires,
            account_id=str(account_id),
        )
        _save_token_file(token)
        return token
    except Exception:
        return None


class _FileLock:
    """Simple file lock to reduce concurrent refreshes."""

    def __init__(self, path: Path):
        self._path = path
        self._fp = None

    def __enter__(self) -> "_FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self._path, "a+")
        try:
            import fcntl

            fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX)
        except Exception:
            # Non-POSIX or failed lock: continue without locking.
            pass
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            import fcntl

            fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            if self._fp:
                self._fp.close()
        except Exception:
            pass


def get_codex_token() -> CodexToken:
    """Get an available token (refresh if needed)."""
    token = _load_token_file() or _try_import_codex_cli_token()
    if not token:
        raise RuntimeError("Codex OAuth credentials not found. Please run the login command.")

    # Refresh 60 seconds early.
    now_ms = int(time.time() * 1000)
    if token.expires - now_ms > 60 * 1000:
        return token

    lock_path = _get_token_path().with_suffix(".lock")
    with _FileLock(lock_path):
        # Re-read to avoid stale token if another process refreshed it.
        token = _load_token_file() or token
        now_ms = int(time.time() * 1000)
        if token.expires - now_ms > 60 * 1000:
            return token
        try:
            refreshed = _refresh_token(token.refresh)
            _save_token_file(refreshed)
            return refreshed
        except Exception:
            # If refresh fails, re-read the file to avoid false negatives.
            latest = _load_token_file()
            if latest and latest.expires - now_ms > 0:
                return latest
            raise


def ensure_codex_token_available() -> None:
    """Ensure a valid token is available; raise if not."""
    _ = get_codex_token()


async def _read_stdin_line() -> str:
    loop = asyncio.get_running_loop()
    if hasattr(loop, "add_reader") and sys.stdin:
        future: asyncio.Future[str] = loop.create_future()

        def _on_readable() -> None:
            line = sys.stdin.readline()
            if not future.done():
                future.set_result(line)

        try:
            loop.add_reader(sys.stdin, _on_readable)
        except Exception:
            return await loop.run_in_executor(None, sys.stdin.readline)

        try:
            return await future
        finally:
            try:
                loop.remove_reader(sys.stdin)
            except Exception:
                pass

    return await loop.run_in_executor(None, sys.stdin.readline)


async def _await_manual_input(
    on_manual_code_input: Callable[[str], None],
) -> str:
    await asyncio.sleep(MANUAL_PROMPT_DELAY_SEC)
    on_manual_code_input("Paste the authorization code (or full redirect URL), or wait for the browser callback:")
    return await _read_stdin_line()


def login_codex_oauth_interactive(
    on_auth: Callable[[str], None] | None = None,
    on_prompt: Callable[[str], str] | None = None,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_manual_code_input: Callable[[str], None] = None,
    originator: str = DEFAULT_ORIGINATOR,
) -> CodexToken:
    """Interactive login flow."""
    async def _login_async() -> CodexToken:
        verifier, challenge = _generate_pkce()
        state = _create_state()

        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": originator,
        }
        url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

        loop = asyncio.get_running_loop()
        code_future: asyncio.Future[str] = loop.create_future()

        def _notify(code_value: str) -> None:
            if code_future.done():
                return
            loop.call_soon_threadsafe(code_future.set_result, code_value)

        server, server_error = _start_local_server(state, on_code=_notify)
        if on_auth:
            on_auth(url)
        else:
            webbrowser.open(url)

        if not server and server_error and on_status:
            on_status(
                f"Local callback server could not start ({server_error}). "
                "You will need to paste the callback URL or authorization code."
            )

        code: str | None = None
        try:
            if server:
                if on_progress and not on_manual_code_input:
                    on_progress("Waiting for browser callback...")

                tasks: list[asyncio.Task[Any]] = []
                callback_task = asyncio.create_task(asyncio.wait_for(code_future, timeout=120))
                tasks.append(callback_task)
                manual_task = asyncio.create_task(_await_manual_input(on_manual_code_input))
                tasks.append(manual_task)

                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

                for task in done:
                    try:
                        result = task.result()
                    except asyncio.TimeoutError:
                        result = None
                    if not result:
                        continue
                    if task is manual_task:
                        parsed_code, parsed_state = _parse_authorization_input(result)
                        if parsed_state and parsed_state != state:
                            raise RuntimeError("State validation failed.")
                        code = parsed_code
                    else:
                        code = result
                    if code:
                        break

            if not code:
                prompt = "Please paste the callback URL or authorization code:"
                if on_prompt:
                    raw = await loop.run_in_executor(None, on_prompt, prompt)
                else:
                    raw = await loop.run_in_executor(None, input, prompt)
                parsed_code, parsed_state = _parse_authorization_input(raw)
                if parsed_state and parsed_state != state:
                    raise RuntimeError("State validation failed.")
                code = parsed_code

            if not code:
                raise RuntimeError("Authorization code not found.")

            if on_progress:
                on_progress("Exchanging authorization code for tokens...")
            token = await _exchange_code_for_token_async(code, verifier)
            _save_token_file(token)
            return token
        finally:
            if server:
                server.shutdown()
                server.server_close()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_login_async())

    result: list[CodexToken] = []
    error: list[Exception] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(_login_async()))
        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]
