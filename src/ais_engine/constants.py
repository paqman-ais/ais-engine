"""Constants for the AIS fuel-usage emission grid.

Ported verbatim from the verified Jupyter logic
(``reference/legacy-jupyter/ais_modules/ais_module.py``).

Spec reference: ``logic-spec/01-core-emission-grid-logic.md`` section 2.
"""

# Notes <-> km/h conversions (spec section 2)
KN_TO_KM = 1.852
KM_TO_KN = 0.539957

# g -> tonne (multiply kW * h * g/kWh result to get tonnes)
SFOC_MULTIPLIER = 0.000001

# Auxiliary engine SFOC is fixed at 185 g/kWh.
AUX_USAGE_FACTOR = 185 * SFOC_MULTIPLIER

# Outlier / stationary / large-gap thresholds (spec section 2).
MAX_SPEED_LIMIT_KN = 30.0      # speed_kn > 30 -> outlier, dropped
STATIONARY_SPEED_KN = 0.3      # main engine: speed_kn <= 0.3 -> usage 0
STATIONARY_SOG_KN = 0.3        # aux/state threshold: sog <= 0.3 considered stopped
LARGE_GAP_HOURS = 1.0          # time_diff_hours >= 1 -> large gap

# Auxiliary engine load-factor branch thresholds (spec section 2).
AUX_SPEED_HIGH_KN = 10.0       # sog >= 10 -> AUX_LF_HIGH
AUX_LF_HIGH = 0.3              # sog >= 10
AUX_LF_MID = 0.5              # 0.3 <= sog < 10
AUX_LF_LOW_TANKER_PAX = 0.6   # sog < 0.3 and ship_type is Tanker/Passenger
AUX_LF_LOW_OTHER = 0.4        # sog < 0.3 otherwise

# Linear-interpolation resampling threshold (spec section 5, create_linear).
# A gap larger than this many seconds breaks a moving segment so it is not
# bridged by interpolation.
INTERP_GAP_THRESHOLD_SECONDS = 3600
