import requests


class WechatMpApiError(RuntimeError):
    def __init__(self, message: str, *, errcode: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.errcode = errcode
        self.payload = payload or {}


class WechatMpApiAdapter:
    base_url = "https://api.weixin.qq.com"

    def get_access_token(self, *, app_id: str, app_secret: str) -> dict:
        response = requests.get(
            f"{self.base_url}/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
            timeout=20,
        )
        payload = response.json()
        if response.status_code >= 400 or "errcode" in payload:
            raise WechatMpApiError(
                "wechat access_token request failed",
                errcode=payload.get("errcode"),
                payload=payload,
            )
        return payload
