"""DashScope Fun-ASR provider 单元合同（注入传输层，不出网）。

锁定的行为：短音频走 Flash 同步端点；超过阈值走异步 提交→轮询→下载；
401/403 产出凭据错误文案；异步任务失败/超时产出可读错误；transcription_url
结果解析出全文与时长。
"""

from __future__ import annotations

import json

import pytest

from app.asr import (
    AsrConfiguration,
    AsrProviderError,
    DashScopeFunAsr,
)

FLASH_THRESHOLD = 300.0


def make_config(**overrides: object) -> AsrConfiguration:
    values: dict[str, object] = {
        "base_url": "https://asr.example",
        "api_key": "test-key",
        "model": "fun-asr",
        "flash_model": "fun-asr-flash",
        "flash_threshold_sec": FLASH_THRESHOLD,
        "poll_interval_sec": 0.0,
        "poll_max_attempts": 5,
    }
    values.update(overrides)
    return AsrConfiguration(**values)  # type: ignore[arg-type]


class StubTransport:
    def __init__(self, responses: list[tuple[int, bytes] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        self.calls.append((method, url))
        if headers:
            assert headers.get("Authorization") == "Bearer test-key"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_flash_sync_mode_for_short_audio() -> None:
    transport = StubTransport(
        [
            (
                200,
                json.dumps(
                    {
                        "output": {"text": "短音频转写结果"},
                        "usage": {"duration": 95},
                    }
                ).encode(),
            )
        ]
    )
    provider = DashScopeFunAsr(make_config(), transport=transport)
    result = provider.transcribe("https://media.example/a.m4a", duration_sec=95.0)

    assert result.text == "短音频转写结果"
    assert result.duration_sec == pytest.approx(95.0)
    method, url = transport.calls[0]
    assert (method, url) == (
        "POST",
        "https://asr.example/api/v1/services/aigc/multimodal-generation/generation",
    )


def test_async_mode_submits_polls_and_downloads() -> None:
    transcription_payload = json.dumps(
        {
            "transcripts": [{"text": "长音频完整转写文本"}],
            "properties": {"original_duration_in_milliseconds": 1_250_000},
        }
    ).encode()
    transport = StubTransport(
        [
            (200, json.dumps({"output": {"task_id": "task-1"}}).encode()),
            (200, json.dumps({"output": {"task_status": "RUNNING"}}).encode()),
            (
                200,
                json.dumps(
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "results": [
                                {
                                    "subtask_status": "SUCCEEDED",
                                    "transcription_url": "https://result.example/r.json",
                                }
                            ],
                        }
                    }
                ).encode(),
            ),
            (200, transcription_payload),
        ]
    )
    provider = DashScopeFunAsr(make_config(), transport=transport)
    result = provider.transcribe("https://media.example/long.mp4", duration_sec=1250.0)

    assert result.text == "长音频完整转写文本"
    assert result.duration_sec == pytest.approx(1250.0)
    assert [method for method, _ in transport.calls] == ["POST", "GET", "GET", "GET"]
    assert transport.calls[1][1].endswith("/api/v1/tasks/task-1")


def test_async_task_id_is_observed_before_polling() -> None:
    events: list[str] = []

    class OrderedTransport(StubTransport):
        def __call__(self, *args, **kwargs):
            if args[0] == "GET":
                events.append("poll")
            return super().__call__(*args, **kwargs)

    transport = OrderedTransport(
        [
            (200, json.dumps({"output": {"task_id": "task-observed"}}).encode()),
            (
                200,
                json.dumps(
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "results": [
                                {
                                    "subtask_status": "SUCCEEDED",
                                    "transcription_url": "https://result.example/observed.json",
                                }
                            ],
                        }
                    }
                ).encode(),
            ),
            (200, b'{"transcripts":[{"text":"ok"}]}'),
        ]
    )
    provider = DashScopeFunAsr(make_config(), transport=transport)

    provider.transcribe(
        "https://media.example/long.mp4",
        duration_sec=400.0,
        on_task_created=lambda task_id: events.append(f"persist:{task_id}"),
    )

    assert events[:2] == ["persist:task-observed", "poll"]


def test_async_observer_failure_keeps_task_id_and_never_polls() -> None:
    transport = StubTransport(
        [(200, json.dumps({"output": {"task_id": "task-db-failure"}}).encode())]
    )
    provider = DashScopeFunAsr(make_config(), transport=transport)

    def fail_to_persist(_task_id: str) -> None:
        raise RuntimeError("database unavailable")

    with pytest.raises(AsrProviderError, match="任务号持久化失败") as caught:
        provider.transcribe(
            "https://media.example/long.mp4",
            duration_sec=400.0,
            on_task_created=fail_to_persist,
        )

    assert caught.value.submission_uncertain is True
    assert caught.value.provider_task_id == "task-db-failure"
    assert transport.calls == [
        ("POST", "https://asr.example/api/v1/services/audio/asr/transcription")
    ]


def test_async_failure_raises_readable_error() -> None:
    transport = StubTransport(
        [
            (200, json.dumps({"output": {"task_id": "task-2"}}).encode()),
            (
                200,
                json.dumps(
                    {
                        "output": {
                            "task_status": "FAILED",
                            "results": [{"subtask_status": "FAILED", "message": "音频无法解析"}],
                        }
                    }
                ).encode(),
            ),
        ]
    )
    provider = DashScopeFunAsr(make_config(), transport=transport)
    with pytest.raises(AsrProviderError, match="音频无法解析") as caught:
        provider.transcribe("https://media.example/bad.mp4", duration_sec=400.0)
    assert caught.value.submission_uncertain is False
    assert caught.value.provider_task_id == "task-2"


def test_async_poll_timeout_raises() -> None:
    responses: list[tuple[int, bytes]] = [
        (200, json.dumps({"output": {"task_id": "task-3"}}).encode())
    ] + [(200, json.dumps({"output": {"task_status": "RUNNING"}}).encode())] * 6
    provider = DashScopeFunAsr(make_config(), transport=StubTransport(responses))
    with pytest.raises(AsrProviderError, match="轮询超时") as caught:
        provider.transcribe("https://media.example/slow.mp4", duration_sec=None)
    assert caught.value.submission_uncertain is True
    assert caught.value.provider_task_id == "task-3"


def test_async_submit_response_loss_is_uncertain_without_provider_id() -> None:
    provider = DashScopeFunAsr(
        make_config(),
        transport=StubTransport([AsrProviderError("语音转写服务连接失败：TimeoutError")]),
    )

    with pytest.raises(AsrProviderError, match="连接失败") as caught:
        provider.transcribe("https://media.example/long.mp4", duration_sec=400.0)

    assert caught.value.submission_uncertain is True
    assert caught.value.provider_task_id is None


def test_async_submit_success_without_task_id_is_uncertain() -> None:
    provider = DashScopeFunAsr(
        make_config(),
        transport=StubTransport([(200, b'{"output":{}}')]),
    )

    with pytest.raises(AsrProviderError, match="未返回任务号") as caught:
        provider.transcribe("https://media.example/long.mp4", duration_sec=400.0)

    assert caught.value.submission_uncertain is True
    assert caught.value.provider_task_id is None


def test_async_poll_transport_error_keeps_provider_task_id_for_reconciliation() -> None:
    provider = DashScopeFunAsr(
        make_config(),
        transport=StubTransport(
            [
                (200, json.dumps({"output": {"task_id": "task-poll"}}).encode()),
                AsrProviderError("语音转写服务连接失败：TimeoutError"),
            ]
        ),
    )

    with pytest.raises(AsrProviderError, match="连接失败") as caught:
        provider.transcribe("https://media.example/long.mp4", duration_sec=400.0)

    assert caught.value.submission_uncertain is True
    assert caught.value.provider_task_id == "task-poll"


def test_async_submit_rejection_is_definite() -> None:
    provider = DashScopeFunAsr(
        make_config(),
        transport=StubTransport([(400, b'{"code":"InvalidParameter"}')]),
    )

    with pytest.raises(AsrProviderError, match="HTTP 400") as caught:
        provider.transcribe("https://media.example/long.mp4", duration_sec=400.0)

    assert caught.value.submission_uncertain is False
    assert caught.value.provider_task_id is None


def test_invalid_credentials_surface_config_error() -> None:
    transport = StubTransport([(401, b'{"code":"Unauthorized"}')])
    provider = DashScopeFunAsr(make_config(), transport=transport)
    with pytest.raises(AsrProviderError, match="凭据无效"):
        provider.transcribe("https://media.example/a.m4a", duration_sec=10.0)


def test_missing_api_key_rejected() -> None:
    provider = DashScopeFunAsr(make_config(api_key=""), transport=StubTransport([]))
    with pytest.raises(AsrProviderError, match="未配置"):
        provider.transcribe("https://media.example/a.m4a", duration_sec=10.0)
