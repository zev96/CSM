def test_split_short(client):
    r = client.post("/api/vault/atomize/split", json={"text": "短文。"})
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"] == ["短文。"]
    assert body["truncated"] is False and body["dropped_chars"] == 0


def test_split_empty(client):
    r = client.post("/api/vault/atomize/split", json={"text": ""})
    assert r.status_code == 200
    assert r.json() == {"chunks": [], "truncated": False, "dropped_chars": 0}


def test_split_long_multi_chunk(client):
    text = "测试句子内容。" * 3000        # 21000 字 > 8000
    r = client.post("/api/vault/atomize/split", json={"text": text})
    assert r.status_code == 200
    chunks = r.json()["chunks"]
    assert len(chunks) >= 2
    assert all(len(c) <= 8000 for c in chunks)


def test_split_missing_text_422(client):
    assert client.post("/api/vault/atomize/split", json={}).status_code == 422


def test_split_default_cap_truncates(client):
    text = "测试句子内容。" * 15000        # 10.5 万字 > 8×8000 可用量
    r = client.post("/api/vault/atomize/split", json={"text": text})
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is True and body["dropped_chars"] > 0
    assert len(body["chunks"]) == 8
