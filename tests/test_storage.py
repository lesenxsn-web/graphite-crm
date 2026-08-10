from src.storage import JsonStore


def test_local_store_round_trip(tmp_path):
    store = JsonStore(data_dir=tmp_path)
    rows = [{"id": "1", "company_name": "测试公司"}]
    store.save("customers", rows)
    assert store.load("customers") == rows
