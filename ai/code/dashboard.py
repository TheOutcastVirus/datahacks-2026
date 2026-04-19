"""Interactive Plotly dashboard for the La Jolla SLA forecast.

Reads `sla_prediction_timeseries.csv` (produced by
simple_dnn_full_history_wide_projection.py) and writes a standalone HTML file
with zoom/pan/range-slider controls. Open the HTML in any browser.

Run: python ai/code/dashboard.py
Output: ai/outputs/plots/sla_dashboard.html
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from project_paths import PLOTS_DIR, SLA_PREDICTION_CSV


CSV = SLA_PREDICTION_CSV
OUT_HTML = PLOTS_DIR / "sla_dashboard.html"


def main() -> None:
    if not CSV.exists():
        raise SystemExit(
            f"{CSV} not found. Run simple_dnn_full_history_wide_projection.py first."
        )
    df = pd.read_csv(CSV, parse_dates=["time"]).set_index("time").sort_index()
    print(f"Loaded {len(df)} rows from {CSV.name}")

    obs_end = df.index[df["observed_msl"].notna()].max()
    val_rows = df[df["is_validation"] == True]
    future_rows = df[df["is_future"] == True]

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(
            "Raw MSL + predicted MSL (zoom to inspect month-by-month variation)",
            "Deseasonalized SLA + predicted residual + 12-mo MA trend",
            "Linear SLR trend vs NN-augmented predicted trend",
        ),
        row_heights=[0.4, 0.3, 0.3],
    )

    # --- Panel 1: raw MSL and predicted MSL -----------------------------------
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["observed_msl"],
            name="observed MSL", mode="lines",
            line=dict(color="#666", width=1),
            opacity=0.7,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=val_rows.index, y=val_rows["predicted_msl"],
            name="predicted MSL (validation)", mode="lines+markers",
            line=dict(color="#d62728", width=1.8),
            marker=dict(size=4),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=future_rows.index, y=future_rows["predicted_msl"],
            name="predicted MSL (future rollout)", mode="lines",
            line=dict(color="#ff7f0e", width=1.6),
        ),
        row=1, col=1,
    )

    # --- Panel 2: deseasonalized SLA + trend ---------------------------------
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["observed_sla_deseasonalized"],
            name="observed deseasonalized SLA", mode="lines",
            line=dict(color="#888", width=0.8),
            opacity=0.55,
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["observed_sla_ma12"],
            name="observed 12-mo MA", mode="lines",
            line=dict(color="#111", width=1.6),
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["predicted_residual"],
            name="NN residual prediction", mode="lines",
            line=dict(color="#d62728", width=1.4),
            connectgaps=False,
        ),
        row=2, col=1,
    )

    # --- Panel 3: trend comparison -------------------------------------------
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["linear_trend_msl"],
            name="linear SLR trend (fit on full record)", mode="lines",
            line=dict(color="#2ca02c", width=1.4, dash="dash"),
        ),
        row=3, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["predicted_trend"],
            name="predicted trend (linear + NN residual)", mode="lines",
            line=dict(color="#d62728", width=1.8),
            connectgaps=False,
        ),
        row=3, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["observed_sla_ma12"],
            name="observed 12-mo MA (overlay)", mode="lines",
            line=dict(color="#111", width=1.2),
            opacity=0.7,
        ),
        row=3, col=1,
    )

    # Plotly's add_vline annotation helper currently breaks on pandas Timestamps.
    obs_end_dt = obs_end.to_pydatetime()
    for row in (1, 2, 3):
        fig.add_shape(
            type="line",
            x0=obs_end_dt,
            x1=obs_end_dt,
            y0=0,
            y1=1,
            xref=f"x{'' if row == 1 else row}",
            yref=f"y{'' if row == 1 else row} domain",
            line=dict(color="#555", dash="dot"),
        )
        fig.add_annotation(
            x=obs_end_dt,
            y=1,
            xref=f"x{'' if row == 1 else row}",
            yref=f"y{'' if row == 1 else row} domain",
            text="obs end",
            showarrow=False,
            yshift=8,
            font=dict(color="#555"),
        )

    fig.update_layout(
        height=900,
        title=dict(
            text="La Jolla sea-level forecast: linear SLR trend + NN residual",
            x=0.02,
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=30, t=80, b=40),
    )
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.04), row=3, col=1)
    fig.update_yaxes(title_text="MSL (m)", row=1, col=1)
    fig.update_yaxes(title_text="SLA (m)", row=2, col=1)
    fig.update_yaxes(title_text="trend (m)", row=3, col=1)

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUT_HTML, include_plotlyjs="cdn", full_html=True)
    print(f"Dashboard written to {OUT_HTML}")
    print(f"Open in browser: file:///{OUT_HTML.as_posix()}")


if __name__ == "__main__":
    main()
