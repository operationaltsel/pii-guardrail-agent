from cs_agent import tools


def test_find_customer_returns_single_partial_name_match(monkeypatch):
    customers = [{"nomor_pelanggan": "1", "no_hp": "08123456789", "nama_pelanggan": "Budi Santoso"}]
    monkeypatch.setattr(tools.db, "all_customers", lambda: customers)

    found = tools._find_customer("Budi")

    assert found == ("1", customers[0])


def test_find_customer_rejects_ambiguous_partial_name(monkeypatch):
    customers = [
        {"nomor_pelanggan": "1", "no_hp": "08123456789", "nama_pelanggan": "Budi Santoso"},
        {"nomor_pelanggan": "2", "no_hp": "08129876543", "nama_pelanggan": "Budi Pratama"},
    ]
    monkeypatch.setattr(tools.db, "all_customers", lambda: customers)

    assert tools._find_customer("Budi") is None
