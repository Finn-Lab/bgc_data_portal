from __future__ import annotations

import base64
import io
from typing import Optional

import pandas as pd
from django.db.models import Q

from ...models import Bgc


def export_bgc_embeddings_base64(n_sample: Optional[int] = None) -> str:
    """Return a base64-encoded Parquet bytestring containing BGC embeddings.

    If n_sample is provided, randomly sample that many embeddings.
    """
    qs = Bgc.objects.filter(Q(is_aggregated_region=True)).values_list("id", "embedding")
    if n_sample is not None:
        qs = qs.order_by("?")[:n_sample]

    data = [
        {"id": pk, "embedding": list(vec) if vec is not None else []} for pk, vec in qs
    ]
    df = pd.DataFrame(data)
    if df.empty:
        return base64.b64encode(b"").decode("ascii")

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
