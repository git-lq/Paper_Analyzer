import os
import sys
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
from urllib.parse import urlparse, parse_qs

class RequestHandler(BaseHTTPRequestHandler):
    # 💡 就是这三行救命代码！彻底切断 Python 试图查询 DNS 的 30 秒卡顿！
    def address_string(self):
        return self.client_address[0]
    
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        
        # 拦截带有 /open 的请求
        if parsed.path == '/open':
            if 'path' in qs:
                file_path = qs['path'][0]
                
                # 检查文件是否存在
                if os.path.exists(file_path):
                    try:
                        # 根据不同的操作系统调用默认程序打开文件
                        if sys.platform == 'win32':
                            os.startfile(file_path) # Windows 完美支持
                        elif sys.platform == 'darwin':
                            subprocess.call(['open', file_path]) # Mac 支持
                        else:
                            subprocess.call(['xdg-open', file_path]) # Linux 支持
                            
                        # 核心体验优化：向浏览器返回一段 JS 代码，让新弹出的网页标签瞬间自动关闭
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(b"<script>window.close();</script>")
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f"打开文件失败: {str(e)}".encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"File not found on this computer.")
            # 🎯 任务 2：处理 Zotero 传来的打开 Obsidian 笔记请求
            else:
                self.send_response(400)
                self.end_headers()
        elif parsed.path == '/obsidian':
            if 'file' in qs:
                file_name = qs['file'][0]
                vault_name = qs['vault'][0]
                
                # 强行对文件名进行安全的 URL 编码，防止中文或空格引发系统调用崩溃
                encoded_vault = urllib.parse.quote(vault_name)
                encoded_file = urllib.parse.quote(file_name)
                obs_uri = f"obsidian://open?vault={encoded_vault}&file={encoded_file}"
                
                # 打印日志，方便我们在黑框里看它到底生成了什么鬼东西
                print(f"🔗 准备唤醒 Obsidian，URI: {obs_uri}")
                
                # 调用系统协议打开 Obsidian
                if sys.platform == 'win32':
                    os.startfile(obs_uri)
                elif sys.platform == 'darwin':
                    subprocess.call(['open', obs_uri])
                else:
                    subprocess.call(['xdg-open', obs_uri])
                    
                # 【核心修复】：无论前面成功与否，必须强行给浏览器返回 200 OK，防止 Empty Response！
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<script>window.close();</script>")
            else:
                print("⚠️ 警告：URL 里没有找到 file 参数")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    port = 18888
    server = HTTPServer(('localhost', port), RequestHandler)
    print(f"🚀 本地文件监听服务器已启动！(端口 {port})")
    print("💡 请保持此黑框在后台运行。")
    print("💡 现在你可以在 Notion 里点击 Local Path 链接，直接秒开本地 PDF 了！")
    server.serve_forever()