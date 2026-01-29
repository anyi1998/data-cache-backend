import requests
import os
from urllib.parse import quote

# Cloudflare Proxy Prefix
# 默认为空，如果在环境变量中设置了 CF_PROXY_URL，则启用代理
# 格式: https://your-worker.workers.dev/proxy/
CF_PROXY_URL = os.environ.get("CF_PROXY_URL", "")

# 原始的 request 方法
_original_request = requests.Session.request

def patched_request(self, method, url, *args, **kwargs):
    """
    拦截 requests 请求，如果是从 akshare 发往东财的请求，并且配置了代理，则走代理
    """
    if CF_PROXY_URL and isinstance(url, str):
        # 识别东财 API域名 (akshare 主要使用这些域名)
        eastmoney_domains = [
            "eastmoney.com",
            "1234567.com.cn",  # 东方财富旗下基金网
            "tiantianfunds.com"
        ]
        
        # 检查是否是东财请求
        if any(domain in url for domain in eastmoney_domains):
            # 避免对已经是代理的请求再次代理
            if CF_PROXY_URL not in url:
                print(f"[PROXY] Redirecting to Cloudflare: {url[:50]}...")
                # 构造代理 URL: Proxy URL + URL Encode(Target URL)
                # 注意：Worker 代码逻辑是 /proxy/https://...
                # requests 会自动处理 url 编码，但为了保险，我们手动 encode 一次或者直接拼接
                # 根据 worker.js: targetPath = url.pathname.replace('/proxy/', '') -> decodeURIComponent
                # 所以我们应该传递 encode 过的 URL
                
                # 简单拼接: https://my-worker.dev/proxy/https%3A%2F%2F...
                encoded_target = quote(url, safe='')
                url = f"{CF_PROXY_URL}{encoded_target}"
                
                # 移除可能导致问题的 headers (如 Host)，让 Worker 自己处理
                if 'headers' in kwargs:
                    headers = kwargs['headers']
                    # 移除 Host，因为它指向了原目标，Cloudflare 可能会拒绝
                    if "Host" in headers:
                        del headers["Host"]
                    # 移除 Referer，Worker 会自己加
                    if "Referer" in headers:
                        del headers["Referer"]

    return _original_request(self, method, url, *args, **kwargs)

def apply_proxy_patch():
    """应用猴子补丁"""
    if CF_PROXY_URL:
        # 只打印域名，不暴露完整路径
        from urllib.parse import urlparse
        domain = urlparse(CF_PROXY_URL).netloc
        print(f"[PROXY] Cloudflare Proxy enabled: {domain}")
        requests.Session.request = patched_request
    else:
        print("[PROXY] CF_PROXY_URL not set, proxy disabled.")

