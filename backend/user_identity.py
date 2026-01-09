# user_identity.py
from fastapi import Request


def get_user_key(request: Request) -> str:
    """
    使用 IP 作为用户标识：
    - 优先使用 X-Forwarded-For（如果有反向代理）
    - 否则用 request.client.host
    """
    # 1) 反向代理场景：取 X-Forwarded-For 头部的第一个 IP
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        # 2) 普通场景：直接用 client.host
        if request.client is not None:
            ip = request.client.host
        else:
            ip = "unknown"

    return ip or "unknown"
