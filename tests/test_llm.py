import asyncio
import json

import pytest

from pvb.extraction.backends.llm import HTTPTransport, LLMBackend
from pvb.schemas.annotations import Decision


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.active = 0
        self.maximum = 0

    async def generate(self, payload, timeout):
        self.calls += 1
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        assert payload["response_format"]["type"] == "json_schema"
        return self.response


def make_backend(tmp_path, transport):
    return LLMBackend(
        transport=transport,
        model="mock",
        provider="test",
        prompt="classify only",
        taxonomy={"version": "1.0.0"},
        cache_dir=tmp_path,
        retries=0,
        requests_per_minute=600000.0,
        concurrency=2,
    )


def test_llm_cache_and_validation(tmp_path, decision_data, synthetic_sample):
    t = FakeTransport(Decision(**decision_data).model_dump_json())
    backend = make_backend(tmp_path, t)
    sample = synthetic_sample("safe synthetic classifier input")
    first = asyncio.run(backend.classify(sample))
    second = asyncio.run(backend.classify(sample))
    assert first == second and t.calls == 1
    assert first.requires_human_review
    backend.prompt = "changed template"
    asyncio.run(backend.classify(sample))
    assert t.calls == 2


@pytest.mark.parametrize("response", ["not JSON", "{}", '{"label":"made_up"}'])
def test_invalid_llm_response(tmp_path, synthetic_sample, response):
    backend = make_backend(tmp_path, FakeTransport(response))
    with pytest.raises(RuntimeError, match="not accepted"):
        asyncio.run(backend.classify(synthetic_sample("synthetic request")))
    assert not list(tmp_path.glob("*.json"))


def test_concurrency(tmp_path, synthetic_sample, decision_data):
    transport = FakeTransport(Decision(**decision_data).model_dump_json())
    backend = make_backend(tmp_path, transport)

    async def run_all():
        return await asyncio.gather(
            *(backend.classify(synthetic_sample(f"sample {i}")) for i in range(6))
        )

    assert len(asyncio.run(run_all())) == 6
    assert transport.maximum <= 2


def test_timeout(tmp_path, synthetic_sample):
    class Slow:
        async def generate(self, payload, timeout):
            await asyncio.sleep(1)

    backend = make_backend(tmp_path, Slow())
    backend.timeout = 0.001
    with pytest.raises(RuntimeError):
        asyncio.run(backend.classify(synthetic_sample("timeout input")))


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@example.org/path",
        "https://example.org?key=secret",
        "file:///tmp/test",
    ],
)
def test_endpoint_credentials_rejected(endpoint):
    with pytest.raises(ValueError):
        HTTPTransport(endpoint, "TEST_CREDENTIAL_ENV")


def test_retry_then_success(tmp_path, synthetic_sample, decision_data):
    class Transient:
        calls = 0

        async def generate(self, payload, timeout):
            self.calls += 1
            if self.calls == 1:
                raise OSError("temporary")
            return Decision(**decision_data).model_dump_json()

    transport = Transient()
    backend = make_backend(tmp_path, transport)
    backend.retries = 1
    asyncio.run(backend.classify(synthetic_sample("retry fixture")))
    assert transport.calls == 2


def test_http_transport_local_server(decision_data):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    response = Decision(**decision_data).model_dump_json()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload["model"] == "fixture"
            body = json.dumps({"choices": [{"message": {"content": response}}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            transport = HTTPTransport(
                f"http://127.0.0.1:{server.server_port}/classify", "NONEXISTENT_TEST_ENV"
            )
            raw = asyncio.run(transport.generate({"model": "fixture"}, 2.0))
            assert Decision.model_validate_json(raw).label == "unsafe_violence"
        finally:
            server.shutdown()
            thread.join()
