import os
from typing import Optional
from opentelemetry import trace
from opentelemetry import metrics

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader
)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter


def init_observability():
    """Initialize OpenTelemetry observability.

    OpenTelemetry Usage docs can be found here:
    https://opentelemetry.io/docs/languages/python/instrumentation/#traces

    These metric and trace providers are setup to target the collector running in
    the docker compose file automatically via the `OTEL_` ENV VARs.
    """

    provider = TracerProvider()
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)
    provider = MeterProvider(metric_readers=[metric_reader])
    metrics.set_meter_provider(provider)

    print("OpenTelemetry observability initialised.")


def increment_counter(
    counter_name: str,
    amount: int,
    tags: Optional[dict] = None,
) -> None:
    meter = metrics.get_meter_provider().get_meter("general")
    counter = meter.create_counter(name=counter_name)
    counter.add(amount, tags)


def record_histogram_value(
    histogram_name: str,
    value: float,
    tags: Optional[dict] = None,
) -> None:
    meter = metrics.get_meter_provider().get_meter("general")
    histogram = meter.create_histogram(name=histogram_name)
    histogram.record(value, tags)
