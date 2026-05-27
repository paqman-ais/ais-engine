"""Linear-interpolation preprocessing (pure, no DB).

Faithful port of the moving/stationary segment split + 1s resampling logic in
``ais_grid_module.create_linear`` / ``resample_and_interpolate_for_fast_sog``.

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 5.
"""

from __future__ import annotations

import pandas as pd

from .constants import INTERP_GAP_THRESHOLD_SECONDS, STATIONARY_SOG_KN


def resample_and_interpolate_fast_sog(fast_sog_df: pd.DataFrame) -> pd.DataFrame:
    """Resample a moving (sog>0.3) segment to 1s + linear-interpolate.

    Faithful to ``resample_and_interpolate_for_fast_sog``: a gap larger than
    ``INTERP_GAP_THRESHOLD_SECONDS`` breaks the segment into sub-groups that are
    resampled independently so a long gap is never bridged by interpolation.

    Requires a ``reg_date`` column (datetime) and ``time_diff_second`` column.
    Returns a DataFrame indexed by position with ``reg_date`` restored.
    """
    df = fast_sog_df.copy()
    df = df.set_index("reg_date")
    groups = df["time_diff_second"].gt(INTERP_GAP_THRESHOLD_SECONDS).cumsum()
    resampled = []

    for _group, subset in df.groupby(groups):
        subset = subset.resample("1s").asfreq()
        subset = subset.interpolate(method="linear")
        subset["reg_date"] = subset.index
        resampled.append(subset)

    if resampled:
        return pd.concat(resampled)
    return df


def build_interpolated_track(ais_df: pd.DataFrame) -> pd.DataFrame:
    """Split into moving/stationary segments, interpolate moving ones, recombine.

    Faithful to the segment loop in ``create_linear`` (spec section 5):
      - status = 1 when sog > 0.3 (moving), else 0 (stopped)
      - consecutive same-status rows form a group
      - moving groups are resampled+interpolated to 1s; stopped groups are kept
        as-is
      - recombine, recompute ``time_diff_second`` from the new ``reg_date`` diff

    Requires columns ``reg_date`` (datetime), ``sog``, ``latitude``,
    ``longitude``. Returns the recombined track ready for
    :func:`ais_engine.fuel.get_pollution_data`.
    """
    df = ais_df.copy()
    df["status"] = (df["sog"] > STATIONARY_SOG_KN).astype(int)
    df["change_point"] = df["status"] != df["status"].shift(1)
    df["group"] = df["change_point"].cumsum()
    df.drop(columns=["change_point"], inplace=True)

    merged: list[pd.DataFrame] = []
    for _group_id, group_data in df.groupby("group"):
        if group_data.empty:
            continue
        if group_data["status"].iloc[0] == 1:
            merged.append(resample_and_interpolate_fast_sog(group_data))
        else:
            merged.append(group_data)

    merge_df = pd.concat(merged, ignore_index=True)
    merge_df.drop(columns=["group", "status"], inplace=True)
    merge_df["time_diff_second"] = merge_df["reg_date"].diff().dt.total_seconds()
    return merge_df
