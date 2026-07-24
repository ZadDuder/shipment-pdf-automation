from __future__ import annotations

from collections.abc import Mapping
from typing import Optional


def validate_submission(
    company: str,
    counts: Mapping[str, int],
) -> Optional[str]:
    """Return a user-facing validation error, or None when upload is valid."""
    if company != "moil":
        return None

    invoice_count = int(counts.get("inv", 0) or 0)
    packing_count = int(counts.get("pac", 0) or 0)
    if invoice_count != 1 or packing_count != 1:
        return (
            "Для MOIL за один запуск нужно загрузить ровно один invoice "
            "и один общий packing.\n"
            f"Сейчас загружено: invoice — {invoice_count}, "
            f"packing — {packing_count}. "
            "Для следующего invoice начните отдельную поставку и снова "
            "приложите к нему этот packing."
        )
    return None
