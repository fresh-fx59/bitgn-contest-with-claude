from bitgn_contest_agent.preflight.response import build_response


def test_build_response_shape():
    out = build_response(summary="hello", data={"a": 1})
    assert out == '{"summary": "hello", "data": {"a": 1}}'


def test_build_response_unicode():
    out = build_response(summary="深圳市", data={"k": "深圳市海云电子"})
    # Must be JSON-decodable unicode (no ascii-escape).
    assert "深圳市" in out
