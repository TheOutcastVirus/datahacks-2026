from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T


CATALOG = "main"
SCHEMA = "sawjess"
RAW_VOLUME_PATH = "/Volumes/main/sawjess/raw/sea_level/*.csv"
BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.sea_level_bronze_monthly"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.sea_level_silver_monthly"
GOLD_TABLE = f"{CATALOG}.{SCHEMA}.sea_level_gold_yearly"
EXPORT_VIEW = f"{CATALOG}.{SCHEMA}.sea_level_demo_curve"
CURVE_ID = "california-demo-default"
SOURCE_STATION_ID = "9410230"
UI_BASELINE_YEAR = 2026
SCIENTIFIC_BASELINE_YEAR = 2000
EXPORT_END_YEAR = 2100


@dataclass(frozen=True)
class AnnualPoint:
    year: int
    absolute_msl_m: float


def _normalize_columns(frame: DataFrame) -> DataFrame:
    for column in frame.columns:
        normalized = column.strip().lower()
        if normalized != column:
            frame = frame.withColumnRenamed(column, normalized)
    return frame


def _optional_column(frame: DataFrame, name: str) -> F.Column:
    return F.col(name) if name in frame.columns else F.lit(None)


def _require_baseline(rows: list[AnnualPoint], year: int) -> float:
    for row in rows:
        if row.year == year:
            return row.absolute_msl_m
    raise ValueError(f"Missing baseline year {year} in annual sea-level output.")


def _compute_slope(points: list[AnnualPoint]) -> float:
    count = len(points)
    if count < 2:
        raise ValueError("Need at least two annual points to extrapolate sea level.")

    sum_x = sum(point.year for point in points)
    sum_y = sum(point.absolute_msl_m for point in points)
    sum_xy = sum(point.year * point.absolute_msl_m for point in points)
    sum_xx = sum(point.year * point.year for point in points)
    denominator = count * sum_xx - sum_x * sum_x
    if denominator == 0:
        raise ValueError("Could not compute extrapolation slope from annual points.")
    return (count * sum_xy - sum_x * sum_y) / denominator


def _validate_monotonic(rows: list[AnnualPoint]) -> None:
    for previous, current in zip(rows, rows[1:]):
        if current.absolute_msl_m < previous.absolute_msl_m:
            raise ValueError(
                f"Sea-level annual mean dropped between {previous.year} and {current.year}."
            )


def ensure_schema(spark: SparkSession) -> None:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")


def build_bronze(spark: SparkSession) -> DataFrame:
    raw = _normalize_columns(
        spark.read.option("header", True).option("inferSchema", True).csv(RAW_VOLUME_PATH)
    )

    bronze = (
        raw.withColumn("source_file", F.input_file_name())
        .withColumn("ingested_at", F.current_timestamp())
        .withColumn("timestamp_raw", F.coalesce(_optional_column(raw, "time"), _optional_column(raw, "timestamp")))
        .withColumn("timestamp", F.date_trunc("month", F.to_timestamp("timestamp_raw")).cast("timestamp"))
        .withColumn("predicted_msl_absolute_m", _optional_column(raw, "predicted_msl").cast("double"))
        .withColumn("predicted_trend_component_m", _optional_column(raw, "predicted_trend").cast("double"))
        .withColumn("predicted_residual_component_m", _optional_column(raw, "predicted_residual").cast("double"))
        .withColumn("seasonal_component_m", _optional_column(raw, "seasonal_climatology").cast("double"))
        .withColumn("observed_msl_m", _optional_column(raw, "observed_msl").cast("double"))
        .withColumn(
            "predicted_msl_absolute_m",
            F.when(
                F.col("predicted_msl_absolute_m").isNotNull(),
                F.col("predicted_msl_absolute_m"),
            ).otherwise(
                F.col("predicted_trend_component_m") + F.col("seasonal_component_m")
            ),
        )
        .withColumn(
            "absolute_msl_m",
            F.coalesce(F.col("predicted_msl_absolute_m"), F.col("observed_msl_m")),
        )
        .withColumn(
            "is_future",
            F.coalesce(_optional_column(raw, "is_future").cast("boolean"), F.lit(False)),
        )
    )

    bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(BRONZE_TABLE)
    return bronze


def build_silver(bronze: DataFrame) -> DataFrame:
    dedupe_window = Window.partitionBy("timestamp").orderBy(
        F.col("ingested_at").desc(), F.col("source_file").desc()
    )

    silver = (
        bronze.filter(F.col("timestamp").isNotNull())
        .filter(F.col("absolute_msl_m").isNotNull())
        .withColumn("row_number", F.row_number().over(dedupe_window))
        .filter(F.col("row_number") == 1)
        .select(
            "timestamp",
            F.col("absolute_msl_m").alias("predicted_msl_absolute_m"),
            "predicted_trend_component_m",
            "predicted_residual_component_m",
            "seasonal_component_m",
            "is_future",
        )
        .withColumn("year", F.year("timestamp"))
        .orderBy("timestamp")
    )

    silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(SILVER_TABLE)
    return silver


def build_gold(spark: SparkSession, silver: DataFrame) -> DataFrame:
    yearly = (
        silver.groupBy("year")
        .agg(
            F.avg("predicted_msl_absolute_m").alias("absolute_msl_m"),
            F.count("*").alias("months_in_year"),
        )
        .filter(F.col("months_in_year") == 12)
        .orderBy("year")
    )

    annual_points = [
        AnnualPoint(year=row["year"], absolute_msl_m=row["absolute_msl_m"])
        for row in yearly.select("year", "absolute_msl_m").collect()
    ]
    if not annual_points:
        raise ValueError("No annual sea-level rows were produced from the monthly silver table.")

    _validate_monotonic([point for point in annual_points if point.year >= UI_BASELINE_YEAR])

    baseline_2000 = _require_baseline(annual_points, SCIENTIFIC_BASELINE_YEAR)
    baseline_2026 = _require_baseline(annual_points, UI_BASELINE_YEAR)

    tail = annual_points[-10:]
    slope = _compute_slope(tail)
    last_year = annual_points[-1].year
    last_absolute = annual_points[-1].absolute_msl_m

    extrapolated_rows = []
    for year in range(last_year + 1, EXPORT_END_YEAR + 1):
        absolute = last_absolute + slope * (year - last_year)
        extrapolated_rows.append(
            {
                "year": year,
                "absolute_msl_m": float(absolute),
                "rise_from_2000_m": float(absolute - baseline_2000),
                "rise_from_2026_m": float(absolute - baseline_2026),
                "is_extrapolated": True,
                "source_station_id": SOURCE_STATION_ID,
                "curve_id": CURVE_ID,
            }
        )

    gold = (
        yearly.filter(F.col("year") <= last_year)
        .withColumn("rise_from_2000_m", F.col("absolute_msl_m") - F.lit(baseline_2000))
        .withColumn("rise_from_2026_m", F.col("absolute_msl_m") - F.lit(baseline_2026))
        .withColumn("is_extrapolated", F.lit(False))
        .withColumn("source_station_id", F.lit(SOURCE_STATION_ID))
        .withColumn("curve_id", F.lit(CURVE_ID))
        .select(
            "year",
            "absolute_msl_m",
            "rise_from_2000_m",
            "rise_from_2026_m",
            "is_extrapolated",
            "source_station_id",
            "curve_id",
        )
    )

    if extrapolated_rows:
        extrapolated_schema = T.StructType(
            [
                T.StructField("year", T.IntegerType(), False),
                T.StructField("absolute_msl_m", T.DoubleType(), False),
                T.StructField("rise_from_2000_m", T.DoubleType(), False),
                T.StructField("rise_from_2026_m", T.DoubleType(), False),
                T.StructField("is_extrapolated", T.BooleanType(), False),
                T.StructField("source_station_id", T.StringType(), False),
                T.StructField("curve_id", T.StringType(), False),
            ]
        )
        gold = gold.unionByName(spark.createDataFrame(extrapolated_rows, extrapolated_schema))

    gold = gold.orderBy("year")
    gold.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(GOLD_TABLE)

    spark.sql(
        f"""
        CREATE OR REPLACE VIEW {EXPORT_VIEW} AS
        SELECT year, absolute_msl_m, rise_from_2000_m, rise_from_2026_m, is_extrapolated, source_station_id, curve_id
        FROM {GOLD_TABLE}
        WHERE year BETWEEN {UI_BASELINE_YEAR} AND {EXPORT_END_YEAR}
        """
    )

    return spark.table(GOLD_TABLE)


def main() -> None:
    spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
    ensure_schema(spark)
    bronze = build_bronze(spark)
    silver = build_silver(bronze)
    build_gold(spark, silver)


if __name__ == "__main__":
    main()
