"""ブラウザ閲覧用の軽量HTTPサーバ。"""

from __future__ import annotations

import json
import mimetypes
import socket
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.logger import get_logger

logger = get_logger(__name__)


class _ThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True


class BrowserHTTPServer:
    """アプリ内データをLAN内ブラウザへ配信するHTTPサーバ。"""

    def __init__(self, provider, host: str = "0.0.0.0", port: int = 8787):
        self.provider = provider
        self.host = host
        self.port = int(port)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> bool:
        if self.httpd is not None:
            return True
        self._stopping.clear()

        try:
            self.httpd = _ThreadingHTTPServer((self.host, self.port), self._make_handler())
        except OSError as e:
            logger.error(f"HTTPサーバ起動失敗: {self.host}:{self.port} {e}")
            self.httpd = None
            return False

        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="BrowserHTTPServer",
            daemon=True,
        )
        self.thread.start()
        logger.info(f"HTTPサーバ起動: http://{self.host}:{self.port}/")
        return True

    def is_running(self) -> bool:
        return self.httpd is not None and self.thread is not None and self.thread.is_alive()

    def stop(self) -> None:
        if self.httpd is None:
            return
        self._stopping.set()
        httpd = self.httpd
        thread = self.thread
        self.httpd = None
        try:
            httpd.shutdown()
            httpd.server_close()
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
        except Exception as e:
            logger.error(f"HTTPサーバ停止エラー: {e}")
        finally:
            self.thread = None
            logger.info("HTTPサーバ停止")

    def _make_handler(self):
        provider = self.provider
        stopping = self._stopping

        class Handler(BaseHTTPRequestHandler):
            server_version = "SirenHelperHTTP/1.0"

            def log_message(self, format, *args):
                logger.debug("HTTP " + format, *args)

            def do_GET(self):
                if stopping.is_set():
                    self._safe_send_error(HTTPStatus.SERVICE_UNAVAILABLE, "server stopping")
                    return

                parsed = urlparse(self.path)
                path = unquote(parsed.path)

                try:
                    if path in ("/", "/index.html"):
                        self._send_file(Path("template") / "browser_viewer.html")
                    elif path == "/api/items":
                        self._send_json(provider.get_http_items_data())
                    elif path == "/api/dungeons":
                        self._send_json(provider.get_http_dungeons_data())
                    elif path.startswith("/api/monsters/"):
                        dungeon_key = path.rsplit("/", 1)[-1]
                        self._send_json(provider.get_http_monsters_data(dungeon_key))
                    elif path == "/api/byoyon/reset-state":
                        self._send_json(provider.get_http_byoyon_reset_state())
                    elif path == "/api/shop-price":
                        self._send_json(provider.get_http_shop_price_data())
                    elif path == "/api/captures":
                        self._send_json(provider.get_http_capture_images_data())
                    elif path == "/api/captures/tile-image":
                        query = parse_qs(parsed.query)
                        filenames = [item for item in query.get("files", []) if item]
                        body = provider.generate_http_capture_tile_image(filenames)
                        if body is None:
                            self._send_error(HTTPStatus.NOT_FOUND, "image not found")
                        else:
                            self._send_body(
                                HTTPStatus.OK,
                                body,
                                "image/jpeg",
                                cache_control="no-store",
                            )
                    elif path.startswith("/api/captures/files/"):
                        filename = path.removeprefix("/api/captures/files/")
                        image_path = provider.get_http_capture_image_path(filename)
                        if image_path is None:
                            self._send_error(HTTPStatus.NOT_FOUND, "image not found")
                        else:
                            self._send_file(image_path)
                    elif path.startswith("/data/icons/"):
                        filename = path.removeprefix("/data/icons/")
                        if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
                            self._send_error(HTTPStatus.NOT_FOUND, "file not found")
                        else:
                            self._send_file(Path("data/icons") / filename)
                    else:
                        self._send_error(HTTPStatus.NOT_FOUND, "not found")
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    logger.debug(f"HTTPクライアント切断: {path}")
                except socket.timeout:
                    logger.debug(f"HTTPクライアントタイムアウト: {path}")
                except Exception as e:
                    logger.error(f"HTTPリクエストエラー: {e}\n{traceback.format_exc()}")
                    self._safe_send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error")

            def do_POST(self):
                if stopping.is_set():
                    self._safe_send_error(HTTPStatus.SERVICE_UNAVAILABLE, "server stopping")
                    return

                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                try:
                    if path != "/api/items/identify":
                        self._send_error(HTTPStatus.NOT_FOUND, "api not found")
                        return

                    length = int(self.headers.get("Content-Length", "0") or "0")
                    raw_body = self.rfile.read(min(length, 1024 * 64))
                    try:
                        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                    except json.JSONDecodeError:
                        self._send_error(HTTPStatus.BAD_REQUEST, "invalid json")
                        return
                    self._send_json(provider.set_http_item_identified(payload))
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    logger.debug(f"HTTPクライアント切断: {path}")
                except Exception as e:
                    logger.error(f"HTTP POSTエラー: {e}\n{traceback.format_exc()}")
                    self._safe_send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error")

            def _send_json(self, data: dict):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self._send_body(
                    HTTPStatus.OK,
                    body,
                    "application/json; charset=utf-8",
                    cache_control="no-store",
                )

            def _send_file(self, path: Path):
                safe_path = Path(path)
                if not safe_path.exists() or not safe_path.is_file():
                    self._send_error(HTTPStatus.NOT_FOUND, "file not found")
                    return
                body = safe_path.read_bytes()
                content_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
                if safe_path.suffix.lower() == ".html":
                    content_type = "text/html; charset=utf-8"
                self._send_body(HTTPStatus.OK, body, content_type, cache_control="no-cache")

            def _send_error(self, status: HTTPStatus, message: str):
                body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
                self._send_body(status, body, "application/json; charset=utf-8")

            def _safe_send_error(self, status: HTTPStatus, message: str):
                try:
                    self._send_error(status, message)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass

            def _send_body(
                self,
                status: HTTPStatus,
                body: bytes,
                content_type: str,
                cache_control: str = "no-store",
            ):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache_control)
                self.end_headers()
                if body:
                    self.wfile.write(body)

        return Handler
