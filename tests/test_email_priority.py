"""Tests for email priority."""

from openpup.email_priority import Email, rank


class TestScoring:
    def test_basic_email(self):
        e = Email(sender="alice@example.com", subject="hello")
        s = e.score()
        # Default score, no bonuses.
        assert s == 1.0

    def test_urgent_term(self):
        e = Email(sender="alice@example.com", subject="URGENT: review needed")
        s = e.score()
        assert s > 1.0

    def test_vip_sender(self):
        e = Email(sender="ceo@example.com", subject="hi")
        s = e.score()
        assert s > 1.0

    def test_long_thread(self):
        e = Email(sender="alice@example.com", subject="hi", thread_count=10)
        s = e.score()
        # 1.0 default + 0.3 * 9 = 3.7 (floating-point approximation)
        assert abs(s - 3.7) < 1e-9

    def test_combined(self):
        e = Email(sender="ceo@x.com", subject="URGENT help", thread_count=5)
        s = e.score()
        # Default 1.0 + urgent 2.0 + vip 1.0 + 4*0.3 = 5.2 -> clamped to 5.0
        assert s == 5.0


class TestRank:
    def test_rank_top_n(self):
        emails = [
            Email(sender="a", subject="hi"),
            Email(sender="ceo@x", subject="URGENT need help", thread_count=5),
            Email(sender="b", subject="lunch"),
        ]
        top = rank(emails, top=2)
        assert len(top) == 2
        # The urgent CEO email should rank first.
        assert top[0][1].sender.startswith("ceo@")

    def test_rank_empty(self):
        assert rank([], top=5) == []
