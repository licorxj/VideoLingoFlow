"""Social frontend 静态文件服务器。

以 /social/ 为 base path 托管 social-auto-upload-web-ui 的构建产物
(frontend/dist)，替代原 Vite dev server。服务器只读磁盘上的 dist，
前端重新构建由更新流程 (npm run build) 负责，构建完成后无需重启本服务。

除静态文件外，其余请求（/api/*、/login、/importAccount/stream 等）代理到
Social 后端 (默认 127.0.0.1:5409)，等价于原 Vite dev server 的 proxy 配置。
这样前端源码里少量相对路径请求（如 EventSource）在静态模式下也能工作，
且不依赖会被 git 更新覆盖的前端源码改动。

用法:
    python social_frontend_server.py --dist <frontend>/dist --port 5173 [--backend-port 5409]
"""
import argparse
import functools
import http.server
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class SocialFrontendHandler(http.server.SimpleHTTPRequestHandler):
    """托管 dist/ 静态文件（/social/ 前缀），其余请求代理到 Social 后端。"""

    backend_url = "http://127.0.0.1:5409"

    # -- 路由 ----------------------------------------------------------

    def _static_path(self, raw_path: str) -> str | None:
        """返回应交给静态文件处理的 path；返回 None 表示应代理到后端。"""
        path = raw_path.split("?", 1)[0].split("#", 1)[0]
        if path == "/social" or path.startswith("/social/"):
            return path
        if path in ("", "/"):
            return "/index.html"
        # 根目录下的静态文件（如 /vite.svg、/favicon.ico）存在则静态处理
        rel = path.lstrip("/")
        if rel and (Path(self.directory) / rel).is_file():
            return path
        return None

    def do_GET(self):
        path = self._static_path(self.path)
        if path is not None:
            self.path = path
            super().do_GET()
        else:
            self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_DELETE(self):
        self._proxy("DELETE")

    def do_OPTIONS(self):
        self._proxy("OPTIONS")

    # -- 静态文件映射 ---------------------------------------------------

    def translate_path(self, path: str) -> str:
        # 去掉 query / hash
        path = path.split("?", 1)[0].split("#", 1)[0]
        try:
            path = urllib.parse.unquote(path)
        except Exception:
            pass
        if path == "/social":
            path = "/social/"
        if path.startswith("/social/"):
            # /social/assets/x.js -> /assets/x.js（对应 dist 下的文件）
            path = path[len("/social"):]
        if path in ("", "/"):
            # 根路径直接给 index.html，方便手动访问 http://127.0.0.1:5173
            path = "/index.html"
        return super().translate_path(path)

    def log_message(self, format: str, *args) -> None:
        # 只输出错误级日志，避免访问日志刷屏
        try:
            code = int(args[0]) if args else 0
        except (TypeError, ValueError):
            code = 0
        if code >= 400:
            super().log_message(format, *args)

    # -- 后端代理 -------------------------------------------------------

    def _proxy(self, method: str) -> None:
        target = self.backend_url + self.path
        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "accept-encoding", "content-length")
        }
        body = None
        clen = self.headers.get("Content-Length")
        if clen:
            try:
                body = self.rfile.read(int(clen))
            except Exception:
                body = None
        req = urllib.request.Request(target, data=body, headers=headers, method=method)
        try:
            # timeout=None：SSE 长连接（如 /importAccount/stream）事件间隔可能很长，
            # 不能设置超时，否则登录/导入进度会在中途断开。
            with urllib.request.urlopen(req, timeout=None) as resp:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/octet-stream"))
                self.send_header("Cache-Control", resp.headers.get("Cache-Control", "no-cache"))
                # 不写 Content-Length，按 HTTP/1.0 语义流式转发（SSE 也依赖连接持续打开）
                self.end_headers()
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except Exception:
                        break
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "text/plain"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(502, f"proxy to {target} failed: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve social frontend dist as static files")
    parser.add_argument("--dist", required=True, help="path to built frontend dist dir")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--backend-port", type=int, default=5409, help="social backend port to proxy non-static requests to")
    args = parser.parse_args()

    dist_dir = Path(args.dist).resolve()
    if not (dist_dir / "index.html").is_file():
        print(f"[SocialFrontend] dist/index.html not found in {dist_dir}; run `npm run build` first.",
              file=sys.stderr)
        return 1

    SocialFrontendHandler.backend_url = f"http://{args.host}:{args.backend_port}"
    handler = functools.partial(SocialFrontendHandler, directory=str(dist_dir))
    with http.server.ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        print(f"[SocialFrontend] static server: http://{args.host}:{args.port}/social/  (dir={dist_dir})")
        print(f"[SocialFrontend] non-static requests proxied to {SocialFrontendHandler.backend_url}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
