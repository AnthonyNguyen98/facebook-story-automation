from app.link_text import select_link_text
from app.music import weighted_pool


def test_link_text_avoids_recent():
    cfg = {"LINK_TEXT_01":"Apply qua đây","LINK_TEXT_02":"Apply đây nhoa","LINK_TEXT_MODE":"AUTO_RANDOM"}
    for _ in range(20):
        assert select_link_text(cfg, {"Apply qua đây"}) == "Apply đây nhoa"


def test_weighted_pool_single():
    cfg = {"POOL_WEIGHT_ENERGETIC":"100", "POOL_WEIGHT_YOUTH":"0"}
    for _ in range(20):
        assert weighted_pool(cfg) == "ENERGETIC"
