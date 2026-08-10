from src.scoring import calculate_lead_score


def test_score_is_bounded():
    customer = {
        "stage": "商务谈判",
        "estimated_annual_demand_tons": 2000,
        "contact_name": "张经理",
        "phone": "13800000000",
        "email": "buyer@example.com",
        "contact_role": "采购经理",
        "last_contact_date": "2099-01-01",
    }
    score = calculate_lead_score(customer)
    assert 0 <= score <= 100
    assert score >= 80


def test_empty_customer_scores_low():
    assert calculate_lead_score({}) <= 10
