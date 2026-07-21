import requests


class WechatMpApiError(RuntimeError):
    def __init__(self, message: str, *, errcode: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.errcode = errcode
        self.payload = payload or {}

    @property
    def is_definitive_rejection(self) -> bool:
        """Only an explicit nonzero WeChat errcode proves the request was rejected."""
        return self.errcode not in (None, 0, "0")


class WechatMpApiAdapter:
    base_url = "https://api.weixin.qq.com"

    def _checked_json(self, response: requests.Response, message: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WechatMpApiError(message) from exc
        if not isinstance(payload, dict):
            raise WechatMpApiError(message, payload={})
        if response.status_code >= 400 or payload.get("errcode", 0) != 0:
            raise WechatMpApiError(message, errcode=payload.get("errcode"), payload=payload)
        return payload

    def get_access_token(self, *, app_id: str, app_secret: str) -> dict:
        try:
            response = requests.get(
                f"{self.base_url}/cgi-bin/token",
                params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
                timeout=20,
            )
        except (requests.RequestException, ValueError) as exc:
            raise WechatMpApiError("wechat access_token request failed") from exc
        return self._checked_json(response, "wechat access_token request failed")

    def upload_permanent_image(self, *, access_token: str, file_path: str) -> dict:
        try:
            with open(file_path, "rb") as image_file:
                response = requests.post(
                    f"{self.base_url}/cgi-bin/material/add_material",
                    params={"access_token": access_token, "type": "image"},
                    files={"media": image_file},
                    timeout=60,
                )
        except (OSError, requests.RequestException) as exc:
            raise WechatMpApiError("wechat permanent image upload failed") from exc
        return self._checked_json(response, "wechat permanent image upload failed")

    def upload_content_image(self, *, access_token: str, file_path: str) -> dict:
        try:
            with open(file_path, "rb") as image_file:
                response = requests.post(
                    f"{self.base_url}/cgi-bin/media/uploadimg",
                    params={"access_token": access_token},
                    files={"media": image_file},
                    timeout=60,
                )
        except (OSError, requests.RequestException) as exc:
            raise WechatMpApiError("wechat content image upload failed") from exc
        return self._checked_json(response, "wechat content image upload failed")

    def add_draft(self, *, access_token: str, article: dict) -> dict:
        try:
            response = requests.post(
                f"{self.base_url}/cgi-bin/draft/add",
                params={"access_token": access_token},
                json={"articles": [article]},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise WechatMpApiError("wechat draft add failed") from exc
        return self._checked_json(response, "wechat draft add failed")

    def submit_publish(self, *, access_token: str, media_id: str) -> dict:
        try:
            response = requests.post(
                f"{self.base_url}/cgi-bin/freepublish/submit",
                params={"access_token": access_token},
                json={"media_id": media_id},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise WechatMpApiError("wechat publish submit failed") from exc
        return self._checked_json(response, "wechat publish submit failed")

    def get_publish_status(self, *, access_token: str, publish_id: str) -> dict:
        try:
            response = requests.post(
                f"{self.base_url}/cgi-bin/freepublish/get",
                params={"access_token": access_token},
                json={"publish_id": publish_id},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise WechatMpApiError("wechat publish status failed") from exc
        return self._checked_json(response, "wechat publish status failed")
