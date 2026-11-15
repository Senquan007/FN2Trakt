from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from app.services.webhooks import (
    build_request,
    detect_format,
    feishu_sign,
    remote_error,
)


class _Endpoint:
    """Duck-typed stand-in for WebhookEndpoint."""

    def __init__(self, url: str, secret: str | None = None, fmt: str | None = None):
        self.url = url
        self.secret = secret
        self.format = fmt


PAYLOAD = {
    "event": "sync.failed",
    "version": "4.1.2",
    "sent_at": "2025-01-02T03:04:05Z",
    "data": {
        "app_user": "admin",
        "trakt_user": "demo",
        "status": "partial",
        "message": "上传 3 条，失败 2 条",
        "uploaded": 3,
        "failed": 2,
        "records": [{"title": "示例电影", "status": "failed", "reason": "未匹配"}],
    },
}


def test_detect_format_from_url():
    assert detect_format("https://open.feishu.cn/open-apis/bot/v2/hook/abc") == "feishu"
    assert detect_format("https://open.larksuite.com/open-apis/bot/v2/hook/abc") == "feishu"
    assert detect_format("https://oapi.dingtalk.com/robot/send?access_token=x") == "dingtalk"
    assert detect_format("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x") == "wecom"
    assert detect_format("https://example.com/fn2trakt") == "generic"


def test_feishu_signature_matches_documented_algorithm():
    # Reference value produced by Feishu's official gen_sign() snippet:
    #   string_to_sign = f"{timestamp}\n{secret}"  (used as the HMAC key,
    #   message is empty, result is Base64 encoded)
    assert feishu_sign("1700000000", "test-secret") == "mbm4Y4oluIPQ00qlBIhX8vAZ0EKv3nw0LuTb91jPL84="


def test_feishu_payload_shape():
    endpoint = _Endpoint("https://open.feishu.cn/open-apis/bot/v2/hook/abc", "test-secret")
    url, body, headers = build_request(endpoint, PAYLOAD)
    data = json.loads(body)

    assert url == endpoint.url
    assert data["msg_type"] == "text"
    assert "示例电影" in data["content"]["text"]
    assert data["timestamp"].isdigit()
    assert data["sign"] == feishu_sign(data["timestamp"], "test-secret")
    # The generic document must not be sent verbatim: Feishu rejects it.
    assert "event" not in data
    assert "X-FN2Trakt-Signature" not in headers


def test_feishu_without_secret_omits_signature():
    endpoint = _Endpoint("https://open.feishu.cn/open-apis/bot/v2/hook/abc")
    _url, body, _headers = build_request(endpoint, PAYLOAD)
    data = json.loads(body)
    assert data["msg_type"] == "text"
    assert "sign" not in data and "timestamp" not in data


def test_dingtalk_signature_is_appended_to_the_url():
    endpoint = _Endpoint(
        "https://oapi.dingtalk.com/robot/send?access_token=token", "SEC123", "dingtalk"
    )
    url, body, _headers = build_request(endpoint, PAYLOAD)
    query = parse_qs(urlparse(url).query)
    assert query["access_token"] == ["token"]
    assert query["timestamp"][0].isdigit()
    assert query["sign"][0]
    assert json.loads(body)["msgtype"] == "markdown"


def test_wecom_payload_is_markdown():
    endpoint = _Endpoint("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x", None, "wecom")
    _url, body, _headers = build_request(endpoint, PAYLOAD)
    data = json.loads(body)
    assert data["msgtype"] == "markdown"
    assert "admin" in data["markdown"]["content"]


def test_generic_payload_keeps_signature_header():
    endpoint = _Endpoint("https://example.com/hook", "secret", "generic")
    _url, body, headers = build_request(endpoint, PAYLOAD)
    assert json.loads(body)["event"] == "sync.failed"
    assert headers["X-FN2Trakt-Signature"].startswith("sha256=")


def test_remote_error_detects_platform_rejections():
    assert remote_error('{"code":19021,"msg":"sign match fail"}').startswith("code=19021")
    assert remote_error('{"code":0,"msg":"success"}') is None
    assert remote_error('{"errcode":0,"errmsg":"ok"}') is None
    assert remote_error('{"errcode":93000,"errmsg":"invalid webhook url"}').startswith("errcode=93000")
    assert remote_error("not json") is None
